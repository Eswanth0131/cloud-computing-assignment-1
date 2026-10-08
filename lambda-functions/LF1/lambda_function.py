import json
import os
import boto3
from datetime import datetime, timezone

sqs = boto3.client("sqs")

QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")


def get_slot(slots, name):
    slot = slots.get(name)

    if not slot:
        return None

    value = slot.get("value", {})

    return (
        value.get("interpretedValue")
        or value.get("originalValue")
    )


def lex_response(intent_name, state, message, slots=None):
    return {
        "sessionState": {
            "dialogAction": {
                "type": "Close"
            },
            "intent": {
                "name": intent_name,
                "state": state,
                "slots": slots or {}
            }
        },
        "messages": [
            {
                "contentType": "PlainText",
                "content": message
            }
        ]
    }


def lambda_handler(event, context):
    print("LEX EVENT:", json.dumps(event))

    session_state = event.get("sessionState", {})
    intent = session_state.get("intent", {})

    intent_name = intent.get("name", "")
    slots = intent.get("slots") or {}

    if intent_name == "GreetingIntent":
        return lex_response(
            intent_name,
            "Fulfilled",
            "Hi there! I'm your Dining Concierge. How can I help you today?",
            slots
        )

    if intent_name == "ThankYouIntent":
        return lex_response(
            intent_name,
            "Fulfilled",
            "You're welcome! Enjoy your meal!",
            slots
        )

    if intent_name == "DiningSuggestionsIntent":

        required_slots = [
            "Location",
            "Cuisine",
            "NumberOfPeople",
            "DiningDate",
            "DiningTime",
            "Email"
        ]

        missing_slots = [
            name for name in required_slots
            if not get_slot(slots, name)
        ]

        if missing_slots:
            return {
                "sessionState": {
                    "dialogAction": {
                        "type": "Delegate"
                    },
                    "intent": {
                        "name": intent_name,
                        "slots": slots
                    }
                }
            }

        request = {
            "Location": get_slot(slots, "Location"),
            "Cuisine": get_slot(slots, "Cuisine"),
            "NumberOfPeople": get_slot(slots, "NumberOfPeople"),
            "DiningDate": get_slot(slots, "DiningDate"),
            "DiningTime": get_slot(slots, "DiningTime"),
            "Email": get_slot(slots, "Email"),
            "Timestamp": datetime.now(timezone.utc).isoformat()
        }

        if not QUEUE_URL:
            return lex_response(
                intent_name,
                "Failed",
                "Sorry, the recommendation service is temporarily unavailable.",
                slots
            )

        try:
            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(request)
            )

            print("SQS MESSAGE SENT:", json.dumps(request))

            return lex_response(
                intent_name,
                "Fulfilled",
                "Perfect! I've received your restaurant preferences. "
                "I'll send your restaurant recommendations to your email shortly!",
                slots
            )

        except Exception as error:
            print("SQS ERROR:", str(error))

            return lex_response(
                intent_name,
                "Failed",
                "Sorry, something went wrong. Please try again later.",
                slots
            )

    return lex_response(
        intent_name,
        "Fulfilled",
        "I'm here to help you find restaurants. What would you like?",
        slots
    )