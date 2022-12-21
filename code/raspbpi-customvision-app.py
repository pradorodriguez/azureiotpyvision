## Application that integrates Camera and Temperature Sensor inputs and sent to Iot Edge Custom Vision Container.
# Prediction are received from IoT Edge Custom Vision via REST, and creates image output with tagged objects.
# Based on Temperature Sensor and Custom Vision prediction, and alert is sent to Iothub.

import io
import time
import datetime

# Camera's Python Library 
from picamera import PiCamera

# From seeed_dht import DHT statement imports the DHT sensor class to interact with a Grove temperature sensor
from seeed_dht import DHT

# Libraries to modify images
import requests
import json

# Libraries to modify images
from matplotlib import pyplot as plt
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import os

# Library to communicate with Iothub
from azure.iot.device import IoTHubDeviceClient, Message

def main():
    # Global Variables
    global camera
    global sensortemp
    
    # Initialize the camera
    camera = PiCamera()
    camera.resolution = (640, 480)
    camera.rotation = 0

    time.sleep(2)    

    # Initialize the Temperature Sensor. Param 1: Specifies sensor type DHT11 sensor. Param 2: connected to digital port D5 on the Grove base hat
    sensortemp = DHT("11", 5)

    # Connect to Iothub using the device connection string. The device must have been created in Iothub first, then get the Primary Connection String from the device.
    # https://learn.microsoft.com/en-us/azure/iot-hub/tutorial-connectivity#check-device-authentication
    connection_string = "<REPLACE-THIS-WITH-THE-DEVICE-CONNECTION-STRING>"
    device_client  = create_client_iothub(connection_string)
    device_client.connect()

    while True:        

        # Read the temperature sensor and store the values in the variables "humid" and "temp"
        humid, temp = ReadTemperatureSensor()

        # If temperature is higher than 32°C, take a picture and send it to Custom Vision Container in Iotedge
        if temp >= 32:
            print(f"Temperature is above 32°C. Proceding to send image to the Custom Vision Analysis container")

            # Create a binary stream variable to hold the image
            image = io.BytesIO()

            # Call the CaptureImage function to take a picture
            new_image, image_prefix = CaptureImage(image)

            # Create an array of the picture taken from CaptureImage function 
            h, w, ch, imagearr = CreateArray(new_image)    

            new_image.seek(0)

            # Send picture taken by CaptureImage function to the Custom Vision Container in Iotedge. Return the JSON response to the "results" variable
            results = CustomVisionQuery(new_image)
            ## Beautify the JSON output:
            # prettyjson = json.dumps(results, indent=4, sort_keys=True)
            # print(prettyjson)

            # Create an image with lines around each detected object with a probability above X%. The position of the lines are determined by bounding box coordinates from the Custom Vision Container and stored by function CreateArray.
            DetectedObjects(h, w, ch, imagearr, results, image_prefix)

            # Create a Dictonary IF temperature is higher than XX% and Custom Vision Probability result is higher than XX%
            visiontempjson = MergeVisionTemperature(results, temp, image_prefix)
            # # Beautify the JSON output:
            # prettyjson = json.dumps(visiontempjson, indent=4, sort_keys=True)
            # print(prettyjson)

            # Create the payload and metadata with the extracted JSON output from the MergeVisionTemperature function
            message = Message(visiontempjson)
            message.content_encoding = "utf-8"
            message.content_type = "application/json"

            # Send the message to Iothub
            device_client.send_message(message)

            print("Sleeping for 30 seconds... ZZZZZZ...")   

            # Suspend activity for 30 seconds
            time.sleep(30)  
        else:
            time.sleep(5)            
              
# Functions called by main()

def CaptureImage(image):   
    # Take a picture and store it in the "image" variable 
    camera.capture(image, 'jpeg')
    image.seek(0)

    # Create a unique name for the image file
    image_prefix = 'img_' + str(time.time())
    image_name = image_prefix + ".jpg"

    with open(image_name, 'wb') as image_file:
        image_file.write(image.read())

    return image, image_prefix

def CreateArray(image_file):
    imagearr = Image.open(image_file)
    h, w, ch = np.array(imagearr).shape
    #print("image array: " ,h, w, ch)

    return h, w, ch, imagearr

def CustomVisionQuery(image_file):
    # IP address of the Azure Custom Vision Prediction Rest API inside Iotedge Custom Vision Container
    prediction_url = "http://192.168.86.79/image"
    headers = { 'Content-Type' : 'application/octet-stream' }

    # Send HTTP POST to Custom Vision Container inside Iotedge
    #image.seek(0)
    try: 
        response = requests.post(prediction_url, headers=headers, data=image_file)    
        results = response.json()
        # print("HTTP response from Custom Vision Container: ", response)
        #print("Raw JSON output from Custom Vision Container: ", results)  
        
        # Show the predictions results from CustomVisionQuery Function
        # Prediction result class: https://learn.microsoft.com/en-us/python/api/azure-cognitiveservices-vision-customvision/azure.cognitiveservices.vision.customvision.prediction.models.prediction?view=azure-python
        for prediction in results['predictions']:
            print(f'{prediction["tagName"]}:\t{prediction["probability"] * 100:.2f}%')
           
    except Exception as err:
        print("Error Found while querying Custom Vision Container: ", err)

    return results

def DetectedObjects(h, w, ch, imagearr, results, image_prefix):
    # Create a figure for the results
    fig = plt.figure(figsize=(8, 8))
    plt.axis('off')

    # Display the image with boxes around each detected object
    draw = ImageDraw.Draw(imagearr)
    lineWidth = int(w/100)
    color = 'magenta'
    for prediction in results['predictions']:
        # Only show objects with a > X% probability
        if (prediction['probability']*100) > 70:
            # Box coordinates and dimensions are proportional - convert to absolutes
            # Bounding Box Class: https://learn.microsoft.com/en-us/python/api/azure-cognitiveservices-vision-customvision/azure.cognitiveservices.vision.customvision.prediction.models.boundingbox?view=azure-python
            left = prediction['boundingBox']['left'] * w 
            top = prediction['boundingBox']['top'] * h 
            height = prediction['boundingBox']['height'] * h
            width =  prediction['boundingBox']['width'] * w
            # Draw the box
            points = ((left,top), (left+width,top), (left+width,top+height), (left,top+height),(left,top))
            draw.line(points, fill=color, width=lineWidth)
            # Add the tag name and probability
            plt.annotate(prediction['tagName'] + ": {0:.2f}%".format(prediction['probability'] * 100),(left,top), backgroundcolor=color)
    plt.imshow(imagearr)
    outputfile = image_prefix + '-op' + '.jpg'

    # Save the image in the current directory with boxes around each detected object
    fig.savefig(outputfile)
    #print('Results saved in ', outputfile)

def ReadTemperatureSensor():
    # Read humidity and temperature from sensor
    humid, temp = sensortemp.read()
    print(f'Humidity: {humid} / Temperature: {temp}°C')
    print()

    return humid, temp

# If probability is above XX% and temperature is above XX°C, send information to iothub
def MergeVisionTemperature(results, temp, image_prefix):
    # Initialize a dictionary to store the prediction results from the Custom Vision Container
    temp_dict = { 'date' : str(datetime.datetime.now()), 'temperature' : temp, 'image' : image_prefix + '.jpg', 'predictions' : [] }    

    for prediction in results['predictions']:
        # Only show objects with a > 70% probability and save them in the dictionary
        if (prediction['probability']*100) > 70 and (bool(prediction['tagName'])):            
            temp_dict['predictions'].append({ 'tagName' : prediction['tagName'], 'probability' : prediction['probability'] })               

    # Create a JSON object from the dictionary variable
    jsonoutput = json.dumps(temp_dict, indent=4, sort_keys=True)
    
    return jsonoutput
    

def create_client_iothub(connection_string):
    # Create an IoT Hub client connection
    client = IoTHubDeviceClient.create_from_connection_string(connection_string)

    return client

# Execute this application
if __name__ == "__main__":
    main()