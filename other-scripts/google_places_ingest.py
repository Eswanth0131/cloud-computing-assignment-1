import os
import time
import json
import boto3
import requests
from datetime import datetime, timezone

API_KEY = os.environ["GOOGLE_PLACES_API_KEY"]

REGION = "us-east-1"
TABLE_NAME = "yelp-restaurants"

URL = "https://places.googleapis.com/v1/places:searchText"

CUISINES = [
    "Italian",
    "Chinese",
    "Japanese",
    "Indian",
    "Mexican",
]

NEIGHBORHOODS = [
    "Financial District",
    "Tribeca",
    "SoHo",
    "Greenwich Village",
    "East Village",
    "Lower East Side",
    "Chelsea",
    "Flatiron District",
    "Midtown",
    "Hell's Kitchen",
    "Upper East Side",
    "Upper West Side",
    "Harlem",
    "Washington Heights",
]

HEADERS = {
    "Content-Type": "application/json",
    "X-Goog-Api-Key": API_KEY,
    "X-Goog-FieldMask": "places.id,nextPageToken",
}

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


def search_restaurants(cuisine, neighborhood):
    restaurants = []
    page_token = None

    for _ in range(3):
        payload = {
            "textQuery": (
                f"{cuisine} restaurants in "
                f"{neighborhood}, Manhattan, New York"
            ),
            "pageSize": 20,
        }

        if page_token:
            payload["pageToken"] = page_token

        response = requests.post(
            URL,
            headers=HEADERS,
            json=payload,
            timeout=30,
        )

        response.raise_for_status()
        data = response.json()

        restaurants.extend(data.get("places", []))

        page_token = data.get("nextPageToken")

        if not page_token:
            break

        time.sleep(2)

    return restaurants


def main():
    unique_ids = set()
    total_saved = 0

    for cuisine in CUISINES:
        for neighborhood in NEIGHBORHOODS:
            print(f"Searching {cuisine} in {neighborhood}...")

            try:
                restaurants = search_restaurants(
                    cuisine,
                    neighborhood,
                )

                with table.batch_writer() as batch:
                    for restaurant in restaurants:
                        place_id = restaurant.get("id")

                        if not place_id:
                            continue

                        if place_id in unique_ids:
                            continue

                        unique_ids.add(place_id)

                        batch.put_item(
                            Item={
                                "BusinessID": place_id,
                                "Cuisine": cuisine,
                                "insertedAtTimestamp": (
                                    datetime.now(
                                        timezone.utc
                                    ).isoformat()
                                ),
                            }
                        )

                        total_saved += 1

                print(
                    f"Unique restaurants collected: "
                    f"{total_saved}"
                )

            except Exception as error:
                print(
                    f"Error searching {cuisine} "
                    f"in {neighborhood}: {error}"
                )

            time.sleep(1)

    print(f"\nDONE! Total unique restaurants: {total_saved}")


if __name__ == "__main__":
    main()