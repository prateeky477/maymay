from fastapi import APIRouter, HTTPException,File,UploadFile
from pymongo import MongoClient
from .settings import config
client = MongoClient(config["MONGO_URI"])
db = client["memedb"]
# print(db)
collection = db["user"]
template=db["template"]
saved=db["saved"]


