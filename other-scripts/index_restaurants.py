import boto3
from collections import Counter
from opensearchpy import OpenSearch, RequestsHttpConnection, helpers
from requests_aws4auth import AWS4Auth

AWS_REGION = "us-east-1"
DYNAMODB_TABLE = "yelp-restaurants"
OPENSEARCH_HOST = (
    "search-dining-concierge-cer5gttcxqcb4gb7czwa26gdry."
    "us-east-1.es.amazonaws.com"
)
INDEX_NAME = "restaurants"


def get_opensearch_client():
    session = boto3.Session(region_name=AWS_REGION)
    credentials = session.get_credentials().get_frozen_credentials()

    auth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        AWS_REGION,
        "es",
        session_token=credentials.token,
    )

    return OpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=60,
    )


def load_restaurants():
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(DYNAMODB_TABLE)

    restaurants = []
    scan_kwargs = {}

    while True:
        response = table.scan(**scan_kwargs)
        restaurants.extend(response.get("Items", []))

        if "LastEvaluatedKey" not in response:
            break

        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    return restaurants


def main():
    client = get_opensearch_client()

    if not client.indices.exists(index=INDEX_NAME):
        client.indices.create(
            index=INDEX_NAME,
            body={
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0
                },
                "mappings": {
                    "properties": {
                        "RestaurantID": {"type": "keyword"},
                        "Cuisine": {"type": "keyword"}
                    }
                }
            },
        )
        print(f"Created OpenSearch index: {INDEX_NAME}")
    else:
        print(f"Index already exists: {INDEX_NAME}")

    restaurants = load_restaurants()
    print(f"Loaded {len(restaurants)} restaurants from DynamoDB")

    counts = Counter()

    actions = []

    for restaurant in restaurants:
        restaurant_id = restaurant.get("BusinessID")
        cuisine = restaurant.get("Cuisine")

        if not restaurant_id or not cuisine:
            continue

        counts[cuisine] += 1

        actions.append({
            "_index": INDEX_NAME,
            "_id": restaurant_id,
            "_source": {
                "RestaurantID": restaurant_id,
                "Cuisine": cuisine
            }
        })

    success, errors = helpers.bulk(
        client,
        actions,
        chunk_size=100,
        request_timeout=60,
        raise_on_error=False,
    )

    client.indices.refresh(index=INDEX_NAME)

    print("\n=== INDEXING RESULTS ===")
    print(f"Successfully indexed: {success}")
    print(f"Failed operations: {len(errors)}")

    for cuisine, count in sorted(counts.items()):
        print(f"{cuisine}: {count}")

    result = client.count(index=INDEX_NAME)
    print(f"\nOpenSearch document count: {result['count']}")

    if errors:
        print("\nFirst indexing error:")
        print(errors[0])


if __name__ == "__main__":
    main()
