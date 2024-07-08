from fastapi import FastAPI, HTTPException, Request, Depends,File,UploadFile,Form
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import bcrypt
from datetime import datetime, timezone, timedelta
from fastapi.responses import JSONResponse
import uuid
from pymongo import MongoClient
from datetime import datetime
from typing import List
from pydantic import BaseModel
from typing import Optional
import boto3
import os
from dotenv import load_dotenv

app = FastAPI()



load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
db = client["memedb"]
# print(db)
collection = db["user"]
template=db["template"]
saved=db["saved"]



s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACESS_KEY"),
    aws_secret_access_key=os.getenv("AWS_SECRET_KEY"),
    region_name=os.getenv("REGION_NAME")
)

s3_bucket_name = os.getenv("S3_BUCKET_NAME")
secret_key = os.getenv("SECRET_KEY")

class User(BaseModel):
    username: str
    password: str
    session_id: Optional[str] = None  

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.add_middleware(
    SessionMiddleware,
    secret_key=secret_key,
    session_cookie="session_cookie",
    same_site="lax",  # Allow cross-site
    max_age=24 * 60 * 60, 
    # domain="localhost",
)



def generate_session_id():
    return str(uuid.uuid4())

def get_current_user(request: Request):
    print(request.session)
    session = request.session
    user = session.get("user")
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

def update_authentication_status(username: str, authenticated: bool):
    collection.update_one({"username": username}, {"$set": {"authenticated": authenticated}})

@app.post("/signup")
async def signup(user_data: User):
    try:
        existing_user = collection.find_one({"username": user_data.username})
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already exists")

        hashed_password = bcrypt.hashpw(user_data.password.encode('utf-8'), bcrypt.gensalt())
        user_data_dict = user_data.dict()
        user_data_dict["password"] = hashed_password.decode('utf-8')  
        user_id = collection.insert_one(user_data_dict).inserted_id

        return {"message": "Signup successful"}

    except HTTPException as e:
        raise e  

    except Exception as e:
        print("Signup Error:", e)
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.post("/login")
async def login(user_data: User, request: Request):
    try:
        user = collection.find_one({"username": user_data.username})

        if user and bcrypt.checkpw(user_data.password.encode('utf-8'), user["password"].encode('utf-8')):
            session_id = user.get("session_id")

            if not session_id:
                # If not, generate a new session ID
                session_id = generate_session_id()
                collection.update_one({"username": user_data.username}, {"$set": {"session_id": session_id}})

            # Update the session with the user data
            
            request.session.update({"user": user_data.username, "session_id": session_id})
            print(request.session)

            return {"data": user_data.username}
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")

    except HTTPException as e:
        raise e  

    except Exception as e:
        print("Login Error:", e)
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.get("/private")
async def private_data(current_user: str = Depends(get_current_user)):
    return {"message": "This is private data", "user": current_user}

@app.post("/logout")
async def logout(request: Request):
    try:
        current_user = get_current_user(request)

        request.session.clear()
        update_authentication_status(current_user, False)

        exp = datetime.now(timezone.utc) - timedelta(days=1)
        response = JSONResponse(content={"message": "Logout successful"})
        response.set_cookie(key="session_cookie", value="", expires=exp)
        return response

    except HTTPException as e:
        raise e  

    except Exception as e:
        print("Logout Error:", e)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.post("/auth")
async def auth_required(request:Request):
    try:
        current_user = get_current_user(request)
        return current_user
    except HTTPException as e:
        raise e
    

@app.get("/temp")
async def get_image():
    # Retrieve all image data from MongoDB
    cursor = template.find({})
    image_data_list =  list(cursor)
    # Format image data for the JSON response
    formatted_data = [
        {
            "title": image_data["title"],
            "s3_url": image_data["s3_url"],
            "filename": image_data["filename"],
        }
        for image_data in image_data_list
    ]

    return JSONResponse(content=formatted_data)

    
@app.post("/upload-image")
async def upload_image(image: UploadFile = File(...), title: str = Form(...)):
    # Upload image to AWS S3
    image_id = str(uuid.uuid4())
    s3_object_key = f"images/{image_id}/{image.filename}"

    # Seek to the beginning of the file
    image.file.seek(0)

    # Upload file to S3 with Content-Type header
    s3.upload_fileobj(
        image.file,
        s3_bucket_name,
        s3_object_key,
        ExtraArgs={'ContentType': image.content_type}
    )

    # Get the S3 URL
    s3_url = f"https://{s3_bucket_name}.s3.amazonaws.com/{s3_object_key}"

    image_data = {
        "image_id": image_id,
        "filename": image.filename,
        "content_type": image.content_type,
        "s3_url": s3_url,
        "title": title,
    }

    result =  template.insert_one(image_data)

    return JSONResponse(content={"message": "Image uploaded successfully", "id": str(result.inserted_id)})


@app.post("/save")
async def save_image(
    image: UploadFile = File(...),
    current_user: str = Depends(get_current_user)
):
    image_id = str(uuid.uuid4())
    try:
        if current_user:
            # Replace spaces in filename with underscores
            filename = image.filename.replace(" ", "_")
            
            image_content = await image.read()
            user_saved_collection = saved.find_one({"username": current_user})

            if not user_saved_collection:
                user_saved_collection = {"username": current_user, "images": []}
            
            # Add the new image data to the saved collection
            s3_object_key = f"images/{image_id}/{filename}"

            # Seek to the beginning of the file
            image.file.seek(0)

            # Upload file to S3 with Content-Type header
            s3.upload_fileobj(
                image.file,
                s3_bucket_name,
                s3_object_key,
                ExtraArgs={'ContentType': image.content_type}
            )

            s3_url = f"https://{s3_bucket_name}.s3.amazonaws.com/{s3_object_key}"
            
            new_image_data = {
                "image_id": image_id,
                "filename": filename,
                "content_type": image.content_type,
                "image": s3_url,
                "timestamp": datetime.now(timezone.utc)
            }

            user_saved_collection["images"].append(new_image_data)

            # Save or update the saved collection in the database
            saved.replace_one({"username": current_user}, user_saved_collection, upsert=True)

            content = {"message": "Image received and processed successfully"}
            return JSONResponse(content=content, status_code=200)
        else:
            raise HTTPException(status_code=401, detail="Not authenticated")

    except HTTPException as e:
        raise e

    except Exception as e:
        print("Save Image Error:", e)
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.get("/saved")
async def get_saved_images(current_user: str = Depends(get_current_user)):
    try:
        if current_user:
            # Find the user's saved collection
            user_saved_collection = saved.find_one({"username": current_user})
            if user_saved_collection:
                # Retrieve all images from the saved collection
                images_data = user_saved_collection.get("images", [])
                if images_data:
                    image_data_list =  list(images_data)
                    # Format image data for the JSON response
                    formatted_data = [
                        {
                            "image_id":image_data["image_id"],
                            "s3_url": image_data["image"],
                            "filename": image_data["filename"],
                        }
                        for image_data in image_data_list
                    ]

                    return JSONResponse(content=formatted_data)
    except HTTPException as e:
        raise e  
    

@app.delete("/delete/{image_id}")
async def delete_image(image_id: str, current_user: str = Depends(get_current_user)):
    if current_user:
        try:
            # Find the user's saved collection
            user_saved_collection = saved.find_one({"username": current_user})

            if user_saved_collection:
                # Find the image with the specified image_id
                deleted_image = None
                for image in user_saved_collection["images"]:
                    if image.get("image_id") == image_id:
                        deleted_image = image
                        break

                if deleted_image:
                    # Delete the image from AWS S3
                    s3_object_key = f"images/{deleted_image['filename']}"
                    s3.delete_object(Bucket="maymaydb", Key=s3_object_key)

                    # Remove the image from the list
                    user_saved_collection["images"] = [img for img in user_saved_collection["images"] if img.get("image_id") != image_id]

                    # Update the saved collection in the database
                    saved.replace_one({"username": current_user}, user_saved_collection, upsert=True)

                    return {"message": "Image deleted successfully"}

                else:
                    raise HTTPException(status_code=404, detail="Image not found")

            else:
                raise HTTPException(status_code=404, detail="User not found")

        except HTTPException as e:
            raise e

        except Exception as e:
            print("Delete Image Error:", e)
            raise HTTPException(status_code=500, detail="Internal Server Error")

    else:
        raise HTTPException(status_code=401, detail="Not authenticated")