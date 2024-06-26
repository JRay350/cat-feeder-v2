#!/usr/bin/python3

# Copyright (c) 2022 Raspberry Pi Ltd
# Author: Alasdair Allan <alasdair@raspberrypi.com>
# SPDX-License-Identifier: BSD-3-Clause

# A TensorFlow Lite example for Picamera2 on Raspberry Pi OS Bullseye
#
# Install necessary dependences before starting,
#
# $ sudo apt update
# $ sudo apt install build-essential
# $ sudo apt install libatlas-base-dev
# $ sudo apt install python3-pip
# $ pip3 install tflite-runtime
# $ pip3 install opencv-python==4.4.0.46
# $ pip3 install pillow
# $ pip3 install numpy
#
# and run from the command line,
#
# $ python3 real_time_with_labels.py --model mobilenet_v2.tflite --label coco_labels.txt
from dannytest import *

import argparse

import cv2
import numpy as np
import tflite_runtime.interpreter as tflite

import signal
import sys
import time
import SSD1306 
from PIL import Image, ImageDraw, ImageFont

from picamera2 import MappedArray, Picamera2, Preview

normalSize = (640, 480)
lowresSize = (320, 240)

rectangles = []

ready_to_feed = True # Flag for when a feeding should be happen. This is used to delay feeding constantly when a cat is in view
last_recorded_feed = time.time() # Used to delay successive calls to catfeeder functions by tracking previous feeding
last_recorded_raccoon = 0
feedings = 0


# OLED display dimensions
OLED_WIDTH = 128
OLED_HEIGHT = 32

oled = SSD1306.SSD1306_128_32() # Initialize OLED Display
racc = False

def ReadLabelFile(file_path):
    with open(file_path, 'r') as f:
        lines = f.readlines()
    ret = {}
    for line in lines:
        pair = line.strip().split(maxsplit=1)
        ret[int(pair[0])] = pair[1].strip()
    return ret


def DrawRectangles(request):
    with MappedArray(request, "main") as m:
        for rect in rectangles:
            print(rect)
            rect_start = (int(rect[0] * 2) - 5, int(rect[1] * 2) - 5)
            rect_end = (int(rect[2] * 2) + 5, int(rect[3] * 2) + 5)
            cv2.rectangle(m.array, rect_start, rect_end, (0, 255, 0, 0))
            if len(rect) == 5:
                text = rect[4]
                font = cv2.FONT_HERSHEY_SIMPLEX
                cv2.putText(m.array, text, (int(rect[0] * 2) + 10, int(rect[1] * 2) + 10),
                            font, 1, (255, 255, 255), 2, cv2.LINE_AA)
                
def print_message(line, message): # Draw OLED message content
    # Clear previous content
    image = Image.new("1", (OLED_WIDTH, OLED_HEIGHT))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    
    # Print the message
    draw.text((0, line * 10), message, font=font, fill=255)
    oled.image(image)
    oled.display()
    
def clear_message(): # Clear OLED message content
    print_message(2, " " * 20)

def InferenceTensorFlow(image, model, output, label=None):
    global rectangles

    if label:
        labels = ReadLabelFile(label)
    else:
        labels = None

    interpreter = tflite.Interpreter(model_path=model, num_threads=2)
    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    # print('Input Details: ', input_details)
    output_details = interpreter.get_output_details()
    # print('Output Details: ', output_details)
    height = input_details[0]['shape'][1]
    width = input_details[0]['shape'][2]
    floating_model = False
    if input_details[0]['dtype'] == np.float32:
        floating_model = True

    rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    initial_h, initial_w, channels = rgb.shape

    picture = cv2.resize(rgb, (width, height))

    input_data = np.expand_dims(picture, axis=0)
    if floating_model:
        input_data = (np.float32(input_data) - 127.5) / 127.5

    interpreter.set_tensor(input_details[0]['index'], input_data)

    interpreter.invoke()

    detected_boxes = interpreter.get_tensor(output_details[1]['index'])
    # print('Detected boxes: ', detected_boxes)
    detected_classes = interpreter.get_tensor(output_details[3]['index'])
    # print('Detected classes: ', detected_classes)
    detected_scores = interpreter.get_tensor(output_details[0]['index'])
    # print('Detected Scores: ', detected_scores)
    num_boxes = interpreter.get_tensor(output_details[2]['index'])
    #print('Num Boxes: ', num_boxes)

    global last_recorded_feed, ready_to_feed, last_recorded_raccoon, racc, feedings, check
    rectangles = []
    for i in range(int(num_boxes)):
        top, left, bottom, right = detected_boxes[0][i]
        classId = int(detected_classes[0][i])
        score = detected_scores[0][i]
        if (time.time() - last_recorded_feed >= 10): # Flag for feeding after a 10 second buffer from the previous feeding
            ready_to_feed = True
        if (racc and time.time() - last_recorded_raccoon >= 5): # If it's been five seconds since you found a raccoon
            GPIO.output(LED, GPIO.LOW) # Turn off the LED
            racc = False # Flag the raccoon as gone
            clear_message()
            print("Raccoon has moved away")
        if score > 0.99:
            xmin = left * initial_w
            ymin = bottom * initial_h
            xmax = right * initial_w
            ymax = top * initial_h
            box = [xmin, ymin, xmax, ymax]
            rectangles.append(box)
            if classId == 1: # In case of a raccoon detection, turn on the LED
#                 setup() # Set up GPIO Pins
                racc = True # Flag a raccoon's presence
                last_recorded_raccoon = time.time() # Take a time stamp of when the raccoon was seen
                GPIO.output(LED, GPIO.HIGH) # Turn on LED
                print_message(1, "Raccoon Detected")

            elif ready_to_feed and classId == 0: # In case of a cat detection and when ready, feed
                clear_message()
                print_message(1, "Cat Detected, Feeding") # Output feeding status to OLED
#                 setup() # Set up GPIO Pins
                openfood()
#                 cleanup()
                last_recorded_feed = time.time() # Update previous feeding time
                ready_to_feed = False # Update feeder flag
                feedings += 1
                clear_message() # Clear OLED
#             elif check == True:
#                 check = False
# #                 setup()
#                 print("Opened Food")
#                 openfood()
# #                 cleanup()
            if labels:
                print(labels[classId], 'score = ', score)
                rectangles[-1].append(labels[classId])
            else:
                print('score = ', score)

# Allows program to pause and clean up before exiting
# def exit_handler(sig, frame):
#     print("Cleaning up...")
#     cleanup() # Cleans up GPIO
#     sys.exit(0)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', help='Path of the detection model.', required=True)
    parser.add_argument('--label', help='Path of the labels file.')
    parser.add_argument('--output', help='File path of the output image.')
    args = parser.parse_args()

    if (args.output):
        output_file = args.output
    else:
        output_file = 'out.jpg'

    if (args.label):
        label_file = args.label
    else:
        label_file = None

    picam2 = Picamera2()
    picam2.start_preview(Preview.QTGL)
    config = picam2.create_preview_configuration(main={"size": normalSize},
                                                 lores={"size": lowresSize, "format": "YUV420"})
    picam2.configure(config)

    stride = picam2.stream_configuration("lores")["stride"]
    picam2.post_callback = DrawRectangles

    picam2.start()
    
    setup() # Set up GPIO Pins to Prevent ISR from erroring
    GPIO.add_event_detect(BUTTON, GPIO.RISING, callback = pressed, bouncetime=100) # ISR to reset the feeder system software
    GPIO.output(LED, GPIO.LOW)
    
    while True:
        if (not racc):
            print_message(1, "Cat Feeder System")
        buffer = picam2.capture_buffer("lores")
        grey = buffer[:stride * lowresSize[1]].reshape((lowresSize[1], stride))
        _ = InferenceTensorFlow(grey, args.model, output_file, label_file)
    
#     signal.signal(signal.SIGINT, exit_handler) # Register callback for CNTRL+C exit handling
#     signal.pause() # Pause the program to have time to clean up

if __name__ == '__main__':
    main()
