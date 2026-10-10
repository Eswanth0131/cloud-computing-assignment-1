import os
import json
import random
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone

import boto3
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth


# ============================================================
# CONFIGURATION
# ============================================================

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-1")

DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
OPENSEARCH_ENDPOINT = os.environ["OPENSEARCH_ENDPOINT"].rstrip("/")
OPENSEARCH_INDEX = os.environ.get("OPENSEARCH_INDEX", "restaurants")

SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
SES_SENDER_EMAIL = os.environ["SES_SENDER_EMAIL"]

sqs = boto3.client("sqs", region_name=REGION)
ses = boto3.client("ses", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)

restaurant_table = dynamodb.Table(DYNAMODB_TABLE)


# ============================================================
# OPENSEARCH
# ============================================================

def search_restaurants(cuisine, count=50):
    """
    Search OpenSearch for restaurants matching the cuisine.
    Return restaurant IDs.
    """

    endpoint = (
        f"{OPENSEARCH_ENDPOINT}/"
        f"{OPENSEARCH_INDEX}/_search"
    )

    query = {
        "size": count,
        "query": {
            "term": {
                "Cuisine": cuisine
            }
        }
    }

    body = json.dumps(query).encode("utf-8")

    session = boto3.Session()
    credentials = session.get_credentials().get_frozen_credentials()

    request = AWSRequest(
        method="POST",
        url=endpoint,
        data=body,
        headers={
            "Content-Type": "application/json"
        }
    )

    SigV4Auth(
        credentials,
        "es",
        REGION
    ).add_auth(request)

    signed_headers = dict(request.headers.items())

    http_request = urllib.request.Request(
        endpoint,
        data=body,
        headers=signed_headers,
        method="POST"
    )

    with urllib.request.urlopen(
        http_request,
        timeout=15
    ) as response:

        result = json.loads(
            response.read().decode("utf-8")
        )

    hits = result.get("hits", {}).get("hits", [])

    restaurant_ids = []

    for hit in hits:

        source = hit.get("_source", {})

        restaurant_id = (
            source.get("RestaurantID")
            or hit.get("_id")
        )

        if restaurant_id:
            restaurant_ids.append(restaurant_id)

    logger.info(
        "OpenSearch returned %s restaurants for %s",
        len(restaurant_ids),
        cuisine
    )

    return restaurant_ids


# ============================================================
# DYNAMODB
# ============================================================

def get_restaurant(restaurant_id):
    """
    Retrieve complete restaurant details directly from DynamoDB.
    No Google Places API calls.
    """

    response = restaurant_table.get_item(
        Key={
            "BusinessID": restaurant_id
        }
    )

    item = response.get("Item")

    if not item:
        logger.warning(
            "Restaurant not found in DynamoDB: %s",
            restaurant_id
        )
        return None

    name = item.get("Name", "")
    address = item.get("Address", "")
    rating = item.get("Rating", "N/A")
    reviews = item.get("NumberOfReviews", 0)
    zip_code = item.get("ZipCode", "")
    cuisine = item.get("Cuisine", "")

    coordinates = item.get("Coordinates", {})

    latitude = coordinates.get("Latitude")
    longitude = coordinates.get("Longitude")

    if not name or not address:
        logger.warning(
            "Restaurant missing required details: %s",
            restaurant_id
        )
        return None

    # Generate a Google Maps search link from the stored
    # restaurant name and address. No API request is made.
    maps_query = urllib.parse.quote_plus(
        f"{name} {address}"
    )

    maps_url = (
        "https://www.google.com/maps/search/?api=1&query="
        + maps_query
    )

    return {
        "id": restaurant_id,
        "name": name,
        "address": address,
        "rating": str(rating),
        "reviews": int(reviews),
        "zip_code": zip_code,
        "cuisine": cuisine,
        "latitude": str(latitude) if latitude is not None else "",
        "longitude": str(longitude) if longitude is not None else "",
        "maps_url": maps_url
    }


# ============================================================
# EMAIL
# ============================================================

def build_email(request_data, restaurants):

    cuisine = request_data.get("Cuisine", "Restaurant")
    location = request_data.get("Location", "Manhattan")
    date = request_data.get("DiningDate", "")
    time = request_data.get("DiningTime", "")
    people = request_data.get("NumberOfPeople", "")

    subject = f"Your {cuisine} Restaurant Recommendations"

    lines = [
        "Hello!",
        "",
        f"Here are your {cuisine} restaurant recommendations "
        f"for {location}.",
        "",
        f"Dining Date: {date}",
        f"Dining Time: {time}",
        f"Number of People: {people}",
        "",
        "Recommended Restaurants:",
        ""
    ]

    for index, restaurant in enumerate(restaurants, start=1):

        lines.extend([
            f"{index}. {restaurant['name']}",
            f"   Address: {restaurant['address']}",
            f"   Cuisine: {restaurant['cuisine']}",
            f"   Rating: {restaurant['rating']} / 5",
            f"   Reviews: {restaurant['reviews']}",
            f"   ZIP Code: {restaurant['zip_code']}",
            f"   Google Maps: {restaurant['maps_url']}",
            ""
        ])

    lines.extend([
        "Enjoy your meal!",
        "",
        "Dining Concierge"
    ])

    return subject, "\n".join(lines)


def send_email(recipient, subject, body):
    """
    Send restaurant recommendations using Amazon SES.
    """

    response = ses.send_email(
        Source=SES_SENDER_EMAIL,
        Destination={
            "ToAddresses": [recipient]
        },
        Message={
            "Subject": {
                "Data": subject,
                "Charset": "UTF-8"
            },
            "Body": {
                "Text": {
                    "Data": body,
                    "Charset": "UTF-8"
                }
            }
        }
    )

    logger.info(
        "SES email sent successfully. Message ID: %s",
        response["MessageId"]
    )

    return response


# ============================================================
# PROCESS DINING REQUEST
# ============================================================

def process_dining_request(request_data):

    cuisine = request_data.get("Cuisine", "").strip()
    recipient = request_data.get("Email", "").strip()

    if not cuisine:
        raise ValueError(
            "Cuisine missing from SQS message"
        )

    if not recipient:
        raise ValueError(
            "Email missing from SQS message"
        )

    logger.info(
        "Processing dining request: cuisine=%s",
        cuisine
    )

    # STEP 1: Search OpenSearch by cuisine.
    restaurant_ids = search_restaurants(
        cuisine=cuisine,
        count=50
    )

    if not restaurant_ids:
        raise ValueError(
            f"No restaurants found for cuisine: {cuisine}"
        )

    # STEP 2: Randomize matching restaurants.
    random.shuffle(restaurant_ids)

    recommendations = []

    # STEP 3: Retrieve restaurant details from DynamoDB.
    for restaurant_id in restaurant_ids:

        if len(recommendations) >= 3:
            break

        try:
            restaurant = get_restaurant(restaurant_id)

            if not restaurant:
                continue

            recommendations.append(restaurant)

        except Exception:
            logger.exception(
                "Failed to retrieve restaurant %s",
                restaurant_id
            )

    if len(recommendations) < 3:
        raise RuntimeError(
            "Unable to retrieve three restaurant recommendations"
        )

    # STEP 4: Build email using DynamoDB details.
    subject, body = build_email(
        request_data,
        recommendations
    )

    # STEP 5: Send email using SES.
    send_email(
        recipient,
        subject,
        body
    )

    logger.info(
        "Successfully processed dining request for %s",
        recipient
    )


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    logger.info("LF2 started")

    processed = 0
    failed = 0

    # Poll SQS for dining requests.
    response = sqs.receive_message(
        QueueUrl=SQS_QUEUE_URL,
        MaxNumberOfMessages=5,
        WaitTimeSeconds=0,
        VisibilityTimeout=90,
        MessageAttributeNames=["All"]
    )

    messages = response.get("Messages", [])

    logger.info(
        "Received %s messages from SQS",
        len(messages)
    )

    for message in messages:

        receipt_handle = message["ReceiptHandle"]

        try:

            request_data = json.loads(
                message["Body"]
            )

            process_dining_request(
                request_data
            )

            # Delete SQS message only after successful email.
            sqs.delete_message(
                QueueUrl=SQS_QUEUE_URL,
                ReceiptHandle=receipt_handle
            )

            processed += 1

        except Exception:

            failed += 1

            logger.exception(
                "Failed to process dining request"
            )

    result = {
        "statusCode": 200,
        "body": json.dumps({
            "processed": processed,
            "failed": failed,
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat()
        })
    }

    logger.info(
        "LF2 completed: %s",
        result
    )

    return result