import os
import time
import random
import boto3
import requests

from decimal import Decimal
from datetime import datetime, timezone
from collections import defaultdict, Counter

from opensearchpy import OpenSearch, RequestsHttpConnection, helpers
from requests_aws4auth import AWS4Auth


# ============================================================
# CONFIGURATION
# ============================================================

AWS_REGION = "us-east-1"

DYNAMODB_TABLE = "yelp-restaurants"

OPENSEARCH_HOST = (
    "search-dining-concierge-cer5gttcxqcb4gb7czwa26gdry."
    "us-east-1.es.amazonaws.com"
)

INDEX_NAME = "restaurants"

GOOGLE_PLACES_API_KEY = os.environ["GOOGLE_PLACES_API_KEY"]

CUISINES = [
    "Italian",
    "Chinese",
    "Japanese",
    "Indian",
    "Mexican",
]

RESTAURANTS_PER_CUISINE = 201

EXPECTED_TOTAL = (
    len(CUISINES) * RESTAURANTS_PER_CUISINE
)

REQUEST_DELAY = 0.1
MAX_RETRIES = 3


# ============================================================
# AWS CLIENTS
# ============================================================

session = boto3.Session(region_name=AWS_REGION)

dynamodb = session.resource("dynamodb")

table = dynamodb.Table(DYNAMODB_TABLE)


def get_opensearch_client():
    credentials = (
        session.get_credentials()
        .get_frozen_credentials()
    )

    auth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        AWS_REGION,
        "es",
        session_token=credentials.token,
    )

    return OpenSearch(
        hosts=[
            {
                "host": OPENSEARCH_HOST,
                "port": 443,
            }
        ],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=60,
    )


# ============================================================
# DYNAMODB FUNCTIONS
# ============================================================

def load_all_restaurants():
    restaurants = []

    scan_kwargs = {}

    while True:
        response = table.scan(**scan_kwargs)

        restaurants.extend(
            response.get("Items", [])
        )

        if "LastEvaluatedKey" not in response:
            break

        scan_kwargs["ExclusiveStartKey"] = (
            response["LastEvaluatedKey"]
        )

    return restaurants


def get_zip_code(address_components):
    for component in address_components:
        if "postal_code" in component.get("types", []):
            return component.get("longText", "")

    return ""


# ============================================================
# GOOGLE PLACES API
# ============================================================

def get_place_details(place_id):
    url = (
        "https://places.googleapis.com/v1/places/"
        + place_id
    )

    headers = {
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": (
            "displayName,"
            "formattedAddress,"
            "location,"
            "rating,"
            "userRatingCount,"
            "addressComponents"
        ),
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


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

    number_of_reviews = details.get(
        "userRatingCount", 0
    )

    zip_code = get_zip_code(
        details.get("addressComponents", [])
    )

    if not name:
        raise ValueError(
            f"Missing restaurant name: {place_id}"
        )

    if not address:
        raise ValueError(
            f"Missing restaurant address: {place_id}"
        )

    if latitude is None or longitude is None:
        raise ValueError(
            f"Missing coordinates: {place_id}"
        )

    coordinates = {
        "Latitude": Decimal(str(latitude)),
        "Longitude": Decimal(str(longitude)),
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
        ConditionExpression=(
            "attribute_exists(BusinessID)"
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
        ExpressionAttributeValues={
            ":name": name,
            ":address": address,
            ":coordinates": coordinates,
            ":reviews": int(number_of_reviews),
            ":rating": Decimal(str(rating)),
            ":zip": zip_code,
            ":updated": datetime.now(
                timezone.utc
            ).isoformat(),
        },
    )

    return name


# ============================================================
# RESTAURANT SELECTION
# ============================================================

def select_restaurants(restaurants):
    grouped = defaultdict(list)

    for restaurant in restaurants:
        cuisine = restaurant.get("Cuisine")

        if cuisine in CUISINES:
            grouped[cuisine].append(restaurant)

    selected = []

    for cuisine in CUISINES:
        candidates = sorted(
            grouped[cuisine],
            key=lambda restaurant: restaurant["BusinessID"],
        )

        rng = random.Random(42)
        rng.shuffle(candidates)

        if len(candidates) < RESTAURANTS_PER_CUISINE:
            raise RuntimeError(
                f"Not enough restaurants for {cuisine}. "
                f"Found {len(candidates)}; "
                f"need {RESTAURANTS_PER_CUISINE}."
            )

        chosen = candidates[:RESTAURANTS_PER_CUISINE]

        selected.extend(chosen)

        print(
            f"{cuisine}: selected {len(chosen)} "
            f"of {len(candidates)}"
        )

    return selected


# ============================================================
# ENRICHMENT
# ============================================================

def enrich_selected_restaurants(selected):
    successful = 0
    failed = []

    total = len(selected)

    print("\nEnriching restaurants...")

    for index, restaurant in enumerate(selected, 1):
        place_id = restaurant["BusinessID"]

        completed = False

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                name = enrich_restaurant(restaurant)

                successful += 1
                completed = True

                if index <= 5:
                    print(f"Saved: {name}")

                break

            except Exception as error:
                print(
                    f"Attempt {attempt}/{MAX_RETRIES} "
                    f"failed for {place_id}: {error}"
                )

                if attempt < MAX_RETRIES:
                    time.sleep(2 ** attempt)

        if not completed:
            failed.append(place_id)

        if index % 50 == 0:
            print(
                f"Progress: {index}/{total} | "
                f"Successful: {successful} | "
                f"Failed: {len(failed)}"
            )

        time.sleep(REQUEST_DELAY)

    print("\n=== ENRICHMENT RESULTS ===")
    print(f"Successful: {successful}")
    print(f"Failed: {len(failed)}")

    return failed


# ============================================================
# DELETE EXTRA DYNAMODB RECORDS
# ============================================================

def delete_extra_dynamodb(extra):
    print(
        f"\nDeleting {len(extra)} extra "
        f"DynamoDB records..."
    )

    with table.batch_writer() as batch:
        for restaurant in extra:
            batch.delete_item(
                Key={
                    "BusinessID": restaurant["BusinessID"]
                }
            )

    print(
        f"Deleted {len(extra)} DynamoDB records."
    )


# ============================================================
# DELETE EXTRA OPENSEARCH DOCUMENTS
# ============================================================

def delete_extra_opensearch(client, extra):
    print(
        f"\nDeleting {len(extra)} extra "
        f"OpenSearch documents..."
    )

    actions = [
        {
            "_op_type": "delete",
            "_index": INDEX_NAME,
            "_id": restaurant["BusinessID"],
        }
        for restaurant in extra
    ]

    success, errors = helpers.bulk(
        client,
        actions,
        chunk_size=100,
        request_timeout=60,
        raise_on_error=False,
    )

    client.indices.refresh(index=INDEX_NAME)

    print(f"OpenSearch deletions: {success}")
    print(f"OpenSearch errors: {len(errors)}")

    if errors:
        print("First OpenSearch error:")
        print(errors[0])

        raise RuntimeError(
            "Some OpenSearch deletions failed."
        )


# ============================================================
# VERIFICATION
# ============================================================

def verify_results(client):
    print("\nVerifying final database counts...")

    restaurants = load_all_restaurants()

    dynamodb_count = len(restaurants)

    cuisine_counts = Counter(
        restaurant.get("Cuisine")
        for restaurant in restaurants
    )

    opensearch_count = client.count(
        index=INDEX_NAME
    )["count"]

    print("\n=== FINAL RESULTS ===")

    print(
        f"DynamoDB restaurants: {dynamodb_count}"
    )

    print(
        f"OpenSearch documents: {opensearch_count}"
    )

    print("\nCuisine distribution:")

    for cuisine in CUISINES:
        print(
            f"{cuisine}: {cuisine_counts[cuisine]}"
        )

    counts_valid = (
        dynamodb_count == EXPECTED_TOTAL
        and opensearch_count == EXPECTED_TOTAL
        and all(
            cuisine_counts[cuisine]
            == RESTAURANTS_PER_CUISINE
            for cuisine in CUISINES
        )
    )

    if counts_valid:
        print(
            "\nSUCCESS! Both databases contain "
            f"{EXPECTED_TOTAL} restaurants."
        )
    else:
        print(
            "\nWARNING: Final counts do not match "
            "the expected totals."
        )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 55)
    print("DINING CONCIERGE RESTAURANT FINALIZATION")
    print("=" * 55)

    print("\nLoading DynamoDB restaurants...")

    restaurants = load_all_restaurants()

    print(
        f"Existing restaurants: {len(restaurants)}"
    )

    client = get_opensearch_client()

    if not client.indices.exists(index=INDEX_NAME):
        raise RuntimeError(
            f"OpenSearch index '{INDEX_NAME}' does not exist."
        )

    print("\nSelecting restaurants...")

    selected = select_restaurants(restaurants)

    selected_ids = {
        restaurant["BusinessID"]
        for restaurant in selected
    }

    extra = [
        restaurant
        for restaurant in restaurants
        if restaurant["BusinessID"] not in selected_ids
    ]

    print("\n=== SELECTION SUMMARY ===")

    print(f"Selected: {len(selected)}")
    print(f"Extra: {len(extra)}")

    if len(selected) != EXPECTED_TOTAL:
        raise RuntimeError(
            "Restaurant selection count is incorrect."
        )

    # --------------------------------------------------------
    # STEP 1: ENRICH
    # --------------------------------------------------------

    failed = enrich_selected_restaurants(selected)

    if failed:
        print(
            "\nSTOPPED: Some restaurant enrichment "
            "requests failed."
        )

        print(
            "No restaurants have been deleted."
        )

        return

    # --------------------------------------------------------
    # STEP 2: DELETE EXTRA DYNAMODB RECORDS
    # --------------------------------------------------------

    delete_extra_dynamodb(extra)

    # --------------------------------------------------------
    # STEP 3: DELETE EXTRA OPENSEARCH DOCUMENTS
    # --------------------------------------------------------

    delete_extra_opensearch(client, extra)

    # --------------------------------------------------------
    # STEP 4: VERIFY
    # --------------------------------------------------------

    verify_results(client)


if __name__ == "__main__":
    main()
