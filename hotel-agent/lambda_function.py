# Copy and paste the entire Python code from the expandable section above
# Make sure to include everything from #!/usr/bin/env python3 to the end
#!/usr/bin/env python3

#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.


"""
Simple Hotel Recommendation Agent - Bonus Module
Recommends hotels based on destination and budget
"""

import json
import os
import boto3
from typing import Dict, Any
from strands import Agent, tool
from strands.session.s3_session_manager import S3SessionManager
# Environment variables
EVENT_BUS_NAME = os.environ.get('EVENT_BUS_NAME', 'multi-agent-bus')

# AWS clients
eventbridge = boto3.client('events')

# Simple hotel database (dummy data)
HOTEL_DATA = {
    "Miami": [
        {"name": "Fontainebleau Miami Beach", "price": 350, "rating": 4.5, "tier": "luxury"},
        {"name": "Hampton Inn Miami Beach", "price": 150, "rating": 4.0, "tier": "mid"},
        {"name": "Budget Inn South Beach", "price": 80, "rating": 3.5, "tier": "budget"}
    ],
    "New York": [
        {"name": "The Plaza Hotel", "price": 500, "rating": 4.8, "tier": "luxury"},
        {"name": "Hilton Midtown", "price": 200, "rating": 4.2, "tier": "mid"},
        {"name": "Pod 51 Hotel", "price": 100, "rating": 3.8, "tier": "budget"}
    ],
    "Los Angeles": [
        {"name": "Beverly Hills Hotel", "price": 600, "rating": 4.9, "tier": "luxury"},
        {"name": "Sheraton Universal", "price": 180, "rating": 4.1, "tier": "mid"},
        {"name": "Motel 6 Hollywood", "price": 70, "rating": 3.2, "tier": "budget"}
    ]
}

@tool(name="find_hotels")
def find_hotels(destination: str, budget_per_night: int) -> Dict[str, Any]:
    """
    Find hotel recommendations based on destination and budget.
    
    Args:
        destination: City name
        budget_per_night: Maximum price per night
        
    Returns:
        Dictionary with hotel recommendations
    """
    print(f"[tool] find_hotels called for {destination} with budget ${budget_per_night}")
    
    # Get hotels for destination
    hotels = HOTEL_DATA.get(destination, [])
    
    if not hotels:
        return {
            "status": "no_hotels_found",
            "message": f"No hotels available for {destination}",
            "recommendations": []
        }
    
    # Filter by budget
    affordable_hotels = [h for h in hotels if h["price"] <= budget_per_night]
    
    if not affordable_hotels:
        # Return cheapest option if nothing fits budget
        affordable_hotels = [min(hotels, key=lambda x: x["price"])]
        message = f"No hotels within ${budget_per_night} budget. Showing cheapest option."
    else:
        message = f"Found {len(affordable_hotels)} hotels within budget"
    
    return {
        "status": "success",
        "destination": destination,
        "budget_per_night": budget_per_night,
        "message": message,
        "recommendations": affordable_hotels
    }

@tool(name="send_email")
def send_email(subject: str, message: str, user_email: str = "workshop-participant@example.com") -> Dict[str, Any]:
    """
    Send a funny hotel recommendation email to the user via SNS.
    
    Args:
        subject: Email subject line
        message: Email body with hotel recommendations (should be funny and engaging)
        user_email: User's email address (optional, defaults to workshop participant)
        
    Returns:
        Dictionary with send status
    """
    print(f"[tool] send_email called - subject: {subject}")
    
    try:
        # Get SNS topic ARN from environment
        sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
        
        if not sns_topic_arn:
            return {
                "status": "error",
                "message": "SNS topic not configured"
            }
        
        # Create SNS client
        sns = boto3.client('sns')
        
        # Publish to SNS topic
        response = sns.publish(
            TopicArn=sns_topic_arn,
            Subject=subject,
            Message=message
        )
        
        message_id = response.get('MessageId')
        print(f"[tool] Email sent successfully - MessageId: {message_id}")
        
        return {
            "status": "success",
            "message": "Email sent successfully",
            "message_id": message_id,
            "recipient": user_email
        }
        
    except Exception as e:
        print(f"[tool] Error sending email: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to send email: {str(e)}"
        }

# Create the agent with a simple system prompt
hotel_agent = Agent(
    model="global.anthropic.claude-sonnet-4-6",
    system_prompt="""You are a witty and entertaining hotel recommendation agent with a great sense of humor. 
    
Your job is to recommend hotels based on the traveler's destination and budget, then send them a FUNNY email about it.

When you receive a booking event:
1. Extract the destination and budget information
2. Use the find_hotels tool to get recommendations
3. Craft a hilarious, engaging email about the hotel options (use puns, jokes, and playful language)
4. Use the send_email tool to send the funny email to the user

Make the email entertaining while still being informative. Use humor, puns, and creative descriptions. 
Think of yourself as a comedian who happens to know a lot about hotels!""",
    tools=[find_hotels, send_email]
)

def lambda_handler(event, context):
    """
    Lambda handler for hotel recommendation agent
    """
    print(f"[event] Received event: {json.dumps(event)}")
    
    try:
        # Extract booking details from EventBridge event
        detail = event.get('detail', {})
        booking_id = detail.get('booking_id') or detail.get('bookingID')
        destination = detail.get('destination', 'Unknown')
        budget = detail.get('budget', 0)
        
        # Calculate budget per night (assume 3 nights average)
        budget_per_night = budget // 6  # Half budget for hotel, divided by 3 nights
        
        print(f"[processing] bookingID={booking_id} destination={destination} budget_per_night=${budget_per_night}")
        
        # Setup S3 session for this booking (same prefix as planner to share context)
        session_manager = S3SessionManager(
            session_id=booking_id,
            bucket=os.environ.get('SESSION_BUCKET', 'multi-agent-session'),
            prefix="planner-sessions",
            region_name=os.environ.get('AWS_REGION', 'us-west-2'),
        )
        hotel_agent.session_manager = session_manager
        hotel_agent.agent_id = f"hotel-agent-{booking_id}"
        print(f"[event] bookingID={booking_id} session manager configured")
        
        # Ask the agent to find hotels and send a funny email
        prompt = f"""A travel booking has been finalized for {destination}!
        
Booking ID: {booking_id}
Destination: {destination}
Budget per night: ${budget_per_night}

Please:
1. Find suitable hotel recommendations
2. Write a HILARIOUS email about these hotels (use puns, jokes, and creative descriptions)
3. Send the funny email to the user

Make it entertaining and memorable!"""
        
        # Get agent response
        response = hotel_agent(prompt)
        
        print(f"[agent_response] {response}")
        
        # Publish hotel recommendations event
        event_data = {
            "booking_id": booking_id,
            "destination": destination,
            "budget_per_night": budget_per_night,
            "agent_recommendation": str(response),
            "timestamp": event.get('time')
        }
        
        eventbridge.put_events(
            Entries=[{
                'Source': 'workshop.hotel-agent',
                'DetailType': 'HotelRecommendationsReady',
                'Detail': json.dumps(event_data),
                'EventBusName': EVENT_BUS_NAME
            }]
        )
        
        print(f"[success] Published HotelRecommendationsReady event for bookingID={booking_id}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Hotel recommendations generated',
                'booking_id': booking_id
            })
        }
        
    except Exception as e:
        print(f"[error] {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }