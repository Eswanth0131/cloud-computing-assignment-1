import os
import time
import boto3
import requests
from decimal import Decimal
from datetime import datetime, timezone

REGION = "us-east-1"
TABLE_NAME = "yelp-restaurants"

API_KEY = os.environ["GOOGLE_PLACES_API_KEY"]

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

FIELD_MASK = (
    "id,displayName,formattedAddress,location,"
    "rating,userRatingCount,addressComponents"
)


def get_all_restaurants():
    restaurants = []

    scan_kwargs = {
        "ProjectionExpression": "BusinessID, Cuisine"
    }

    while True:
        response = table.scan(**scan_kwargs)

        restaurants.extend(response.get("Items", []))

        if "LastEvaluatedKey" not in response:
            break

        scan_kwargs["ExclusiveStartKey"] = (
            response["LastEvaluatedKey"]
        )

    return restaurants


def get_place_details(place_id):
    url = (
        "https://places.googleapis.com/v1/places/"
        + place_id
    )

    response = requests.get(
        url,
        headers={
            "X-Goog-Api-Key": API_KEY,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def get_zip_code(address_components):
    for component in address_components:
        if "postal_code" in component.get("types", []):
            return component.get("longText", "")

    return ""


def enrich_restaurant(restaurant):
    place_id = restaurant["BusinessID"]

    details = get_place_details(place_id)

    name = details.get(
        "displayName", {}
    ).get("text", "")

    address = details.get(
        "formattedAddress", ""
    )

    location = details.get("location", {})

    latitude = location.get("latitude")
    longitude = location.get("longitude")

    rating = details.get("rating", 0)
    reviews = details.get("userRatingCount", 0)

    zip_code = get_zip_code(
        details.get("addressComponents", [])
    )

    coordinates = {}

    if latitude is not None:
        coordinates["Latitude"] = Decimal(str(latitude))

    if longitude is not None:
        coordinates["Longitude"] = Decimal(str(longitude))

    update_values = {
        ":name": name,
        ":address": address,
        ":coordinates": coordinates,
        ":reviews": int(reviews),
        ":rating": Decimal(str(rating)),
        ":zip": zip_code,
        ":updated": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    table.update_item(
        Key={
            "BusinessID": place_id
        },
        UpdateExpression=(
            "SET #name = :name, "
            "#address = :address, "
            "#coordinates = :coordinates, "
            "#reviews = :reviews, "
            "#rating = :rating, "
            "#zip = :zip, "
            "#updated = :updated"
        ),
        ExpressionAttributeNames={
            "#name": "Name",
            "#address": "Address",
            "#coordinates": "Coordinates",
            "#reviews": "NumberOfReviews",
            "#rating": "Rating",
            "#zip": "ZipCode",
            "#updated": "detailsUpdatedAt",
        },
        ExpressionAttributeValues=update_values,
        ConditionExpression="attribute_exists(BusinessID)",
    )

    return name


def main():
    restaurants = get_all_restaurants()

    total = len(restaurants)

    print(f"Found {total} existing restaurants.")

    successful = 0
    failed = 0

    for index, restaurant in enumerate(restaurants, 1):
        place_id = restaurant["BusinessID"]

        for attempt in range(3):
            try:
                name = enrich_restaurant(restaurant)

                successful += 1

                if index <= 5:
                    print(f"Saved: {name}")

                break

            except Exception as error:
                if attempt == 2:
                    failed += 1
                    print(
                        f"FAILED {place_id}: {error}"
                    )
                else:
                    time.sleep(2 ** attempt)

        if index % 100 == 0:
            print(
                f"Progress: {index}/{total} | "
                f"Successful: {successful} | "
                f"Failed: {failed}"
            )

        time.sleep(0.1)

    print("\n========== COMPLETE ==========")
    print(f"Total restaurants: {total}")
    print(f"Successfully enriched: {successful}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
