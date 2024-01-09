from .settings import config
import boto3


s3=boto3.client("s3", aws_access_key_id=config["AWS_ACESS_KEY"], aws_secret_access_key=config["AWS_SECRET_KEY"], region_name=config["REGION_NAME"])
s3_bucket_name=config["S3_BUCKET_NAME"]
secret_key=config["SECRET_KEY"]
react_url=config["REACT_APP_URL"]
