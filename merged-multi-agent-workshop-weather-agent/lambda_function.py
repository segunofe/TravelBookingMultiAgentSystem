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
Weather Agent - Weather analysis for flight booking with session management
"""

import json
import os
import uuid
import boto3
from datetime import datetime
from typing import Dict, Any
from strands import Agent, tool, ToolContext
from strands.session.s3_session_manager import S3SessionManager
from strands.models.bedrock import BedrockModel

# Environment variables
EVENT_BUS_NAME = os.environ.get('EVENT_BUS_NAME', 'multi-agent-bus')
STACK_NAME = os.environ.get('STACK_NAME', 'workshop')
SESSION_BUCKET = os.environ.get('SESSION_BUCKET', 'multi-agent-workshop-sessions-us-east-2')
AWS_REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-2')

# AWS clients
eventbridge = boto3.client('events')

class WeatherTools:
    """Weather analysis tools with session state"""
    
    def __init__(self, booking_id: str, session_manager: S3SessionManager = None):
        self.booking_id = booking_id
        self.session_manager = session_manager
        self.weather_data = self._load_weather_data()
    
    def _load_weather_data(self):
        """Load weather data from JSON file"""
        try:
            with open('data.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"[event] bookingID={self.booking_id} weather data.json not found, using fallback data")
            return {
                "weather_data": {
                    'JFK-SEA': {'temp': 60, 'conditions': 'fair', 'risk': 'LOW', 'humidity': 50, 'wind': '10 mph'},
                    'JFK-SFO': {'temp': 65, 'conditions': 'clear', 'risk': 'LOW', 'humidity': 45, 'wind': '8 mph'},
                    'LAX-NYC': {'temp': 55, 'conditions': 'cloudy', 'risk': 'MEDIUM', 'humidity': 70, 'wind': '15 mph'}
                },
                "airport_codes": {
                    "Seattle": "SEA", "New York": "JFK", "San Francisco": "SFO"
                },
                "risk_recommendations": {
                    "LOW": "Good conditions for travel",
                    "MEDIUM": "Monitor weather updates", 
                    "HIGH": "Consider alternative dates"
                }
            }
    
    @tool(name="get_weather", context=True)
    def get_weather(self, origin: str, destination: str, travel_date: str, tool_context: ToolContext) -> dict:
        """
        Get weather forecast for flight route
        
        Args:
            origin: Origin airport code (e.g., 'JFK')
            destination: Destination airport code (e.g., 'SEA') 
            travel_date: Travel date in YYYY-MM-DD format
            tool_context: Strands tool context
        
        Returns:
            Weather analysis with risk assessment
        """
        print(f"[tools] bookingID={self.booking_id} get_weather -> origin={origin}, dest={destination}, date={travel_date}")
        
        # Get weather data from loaded JSON
        weather_data = self.weather_data.get('weather_data', {})
        risk_recommendations = self.weather_data.get('risk_recommendations', {})
        
        # Try different route combinations
        route_key = f"{origin}-{destination}"
        if route_key not in weather_data:
            # Try with airport code mapping
            airport_codes = self.weather_data.get('airport_codes', {})
            dest_code = airport_codes.get(destination, destination)
            route_key = f"{origin}-{dest_code}"
        
        weather = weather_data.get(route_key, {
            'temp': 60, 'conditions': 'fair', 'risk': 'LOW', 
            'humidity': 50, 'wind': '10 mph'
        })
        
        result = {
            'route': f"{origin} → {destination}",
            'date': travel_date,
            'temperature': weather['temp'],
            'conditions': weather['conditions'],
            'risk_level': weather['risk'],
            'humidity': weather.get('humidity', 50),
            'wind': weather.get('wind', '10 mph'),
            'recommendation': risk_recommendations.get(weather['risk'], 'Monitor weather conditions')
        }
        
        print(f"[tools] bookingID={self.booking_id} get_weather <- risk={weather['risk']}, temp={weather['temp']}, conditions={weather['conditions']}")
        return result
    
    @tool(name="publish_event", context=True)
    def publish_event(self, event_type: str, event_data: Dict[str, Any], tool_context: ToolContext) -> Dict[str, Any]:
        """Publish weather analysis events"""
        try:
            print(f"[tools] bookingID={self.booking_id} publish_event -> event_type={event_type}")
            
            response = eventbridge.put_events(
                Entries=[{
                    'Source': 'workshop.weather-agent',
                    'DetailType': event_type,
                    'Detail': json.dumps(event_data),
                    'EventBusName': EVENT_BUS_NAME
                }]
            )
            
            event_id = response['Entries'][0].get('EventId')
            print(f"[action] bookingID={self.booking_id} emitted_event={event_type} event_id={event_id}")
            
            result = {
                'status': 'success',
                'event_type': event_type,
                'event_id': event_id
            }
            return result
            
        except Exception as e:
            print(f"[action] bookingID={self.booking_id} failed_event={event_type} error={str(e)}")
            return {'status': 'error', 'message': str(e)}

def detect_event_type(event: Dict[str, Any]) -> str:
    """Detect the type of event received"""
    
    # EventBridge choreography events
    if 'source' in event and 'detail-type' in event:
        detail_type = event.get('detail-type', '')
        
        if detail_type == 'DatesFinalized':
            return 'dates_finalized'
    
    # Direct invocation
    if 'bookingID' in event and 'origin' in event and 'destination' in event:
        return 'direct_request'
    
    return 'unknown'

def handle_dates_finalized(event: Dict[str, Any]) -> Dict[str, Any]:
    """Handle DatesFinalized event from planner agent"""
    detail = event.get('detail', {})
    booking_id = detail.get('bookingID', str(uuid.uuid4()))
    origin = detail.get('origin', 'JFK')
    destination = detail.get('destination', 'Seattle')
    travel_dates = detail.get('travel_dates', {})
    travel_date = travel_dates.get('departure') or travel_dates.get('start', '2026-09-15')
    
    print(f"[event] bookingID={booking_id} weather analysis requested for {origin} → {destination} on {travel_date}")
    
    # Create S3 session manager
    session_manager = S3SessionManager(
        session_id=booking_id,
        bucket=SESSION_BUCKET,
        prefix="weather-sessions",
        region_name=AWS_REGION
    )
    
    # Create agent with session management and weather tools
    tools = WeatherTools(booking_id, session_manager)
    model = BedrockModel(model_id="global.anthropic.claude-sonnet-4-6")
    agent = Agent(
        agent_id="weather-analyzer",  # Consistent agent ID for session restoration
        name="weather-agent",
        model=model,
        session_manager=session_manager,
        system_prompt="""You are a weather analysis agent for flight booking. 

Analyze weather conditions for the requested flight route and date using the get_weather tool.
Provide a comprehensive weather analysis including risk assessment.
Then publish a WeatherAnalysisCompleted event with your findings using the publish_event tool.""",
        tools=[tools.get_weather, tools.publish_event]
    )
    
    # Process weather analysis request
    prompt = f"""
    Analyze weather conditions for flight booking:
    - Route: {origin} to {destination}
    - Travel Date: {travel_date}
    - Booking ID: {booking_id}
    
    1. Use get_weather tool to check conditions
    2. Provide detailed weather analysis with risk assessment
    3. Publish WeatherAnalysisCompleted event with your analysis
    """
    
    print("=" * 80)
    print(f"[WEATHER AGENT] bookingID={booking_id} - Agent Response START")
    print("=" * 80)
    response = agent(prompt)
    print()  # Line break after response
    print("=" * 80)
    print(f"[WEATHER AGENT] bookingID={booking_id} - Agent Response END")
    print("=" * 80)
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Weather analysis completed with session',
            'booking_id': booking_id,
            'status': 'analysis_completed',
            'session_stored': True,
            'response': str(response)
        })
    }

def lambda_handler(event, context):
    """Main Lambda handler with proper event detection and session management"""
    try:
        # Extract booking ID for consistent logging
        detail = event.get('detail', {}) if 'detail' in event else event
        if isinstance(detail, str):
            detail = json.loads(detail)
        booking_id = detail.get('bookingID', 'unknown')
        print(f"[event] bookingID={booking_id} weather agent received event")
        
        # Detect event type
        event_type = detect_event_type(event)
        print(f"[event] bookingID={booking_id} detected event type: {event_type}")
        
        # Route to appropriate handler
        if event_type == 'dates_finalized':
            return handle_dates_finalized(event)
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': f'Unknown event type: {event_type}',
                    'event': event
                })
            }
            
    except Exception as e:
        print(f"[event] bookingID=unknown weather agent error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'message': 'Weather agent error'
            })
        }

if __name__ == "__main__":
    """Local testing - simulates EventBridge DatesFinalized event"""
    test_event = {
        'detail': {
            'bookingID': 'local-test-001',
            'origin': 'JFK',
            'destination': 'Seattle',
            'travel_dates': {
                'start': '2026-09-15',
                'end': '2026-09-18'
            }
        }
    }
    
    print("=" * 60)
    print("WEATHER AGENT - LOCAL TEST")
    print("=" * 60)
    result = lambda_handler(test_event, None)
    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(json.dumps(result, indent=2))