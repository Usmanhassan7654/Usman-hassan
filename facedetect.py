# -*- coding: utf-8 -*-
"""
Created on Sun Jan 17 20:36:27 2021

@author: Usman Hassan
"""

import cv2 

face_cascade=cv2.CascadeClassifier("D:\Deskcopy\Bilal project\haarcascade_frontalface_default.xml")

def detect_face(img):   #a function to detect face 
    face_img=img.copy() #creating a copy of image to prevent any damage to the original image
    
    face_rect=face_cascade.detectMultiScale(face_img,scaleFactor=1.2,minNeighbors=6) #to make face rectangle
    
    for (x,y,w,h) in face_rect: #to look for points of rectangale that is detecting face,x=horiz y=vert, w=width changed,h=hight changed
        cv2.rectangle(face_img,(x,y),(x+w,y+h),(0,0,255), 15)
    return face_img

img=cv2.imread('group1.jpg',0)
img1=cv2.resize(img, (580,720))
result=detect_face(img1)

cv2.imshow('img',result)
print(img1)
c=cv2.waitKey(0) & 0xFF

if c==27:
    cv2.destroyAllWindows()
    
