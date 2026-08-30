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
Flight Manager Agent - Flight search and booking with session management
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

class FlightTools:
    """Flight search and booking tools with session state"""
    
    def __init__(self, booking_id: str, session_manager: S3SessionManager = None):
        self.booking_id = booking_id
        self.session_manager = session_manager
        self.flight_data = self._load_flight_data()
    
    def _load_flight_data(self):
        """Load flight data from JSON file"""
        try:
            with open('data.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"[event] bookingID={self.booking_id} flight data.json not found, using fallback data")
            return {
                "flights": {
                    'JFK-SEA': [
                        {'airline': 'Delta', 'flight': 'DL123', 'price': 450, 'departure': '08:00', 'arrival': '11:30'},
                        {'airline': 'United', 'flight': 'UA789', 'price': 380, 'departure': '14:15', 'arrival': '17:45'}
                    ],
                    'JFK-SFO': [
                        {'airline': 'Delta', 'flight': 'DL456', 'price': 420, 'departure': '09:00', 'arrival': '12:30'},
                        {'airline': 'United', 'flight': 'UA123', 'price': 390, 'departure': '15:00', 'arrival': '18:30'}
                    ]
                },
                "airlines": {
                    "Delta": {"code": "DL", "rating": 4.2, "preference": "premium"},
                    "United": {"code": "UA", "rating": 3.9, "preference": "value"}
                },
                "airport_codes": {
                    "Seattle": "SEA", "New York": "JFK", "San Francisco": "SFO"
                }
            }
    
    @tool(name="search_flights", context=True)
    def search_flights(self, origin: str, destination: str, travel_date: str, budget: float, travelers: int = 2, tool_context: ToolContext = None) -> dict:
        """
        Search for available flights
        
        Args:
            origin: Origin airport code (e.g., 'JFK')
            destination: Destination airport code (e.g., 'SEA')
            travel_date: Travel date in YYYY-MM-DD format
            budget: Maximum budget for the flight
            travelers: Number of travelers
            tool_context: Strands tool context
        
        Returns:
            Available flight options
        """
        print(f"[tools] bookingID={self.booking_id} search_flights -> origin={origin}, dest={destination}, date={travel_date}, budget={budget}, travelers={travelers}")
        
        # Get flight data from loaded JSON
        flights = self.flight_data.get('flights', {})
        airlines = self.flight_data.get('airlines', {})
        airport_codes = self.flight_data.get('airport_codes', {})
        
        # Try different route combinations
        route_key = f"{origin}-{destination}"
        if route_key not in flights:
            # Try with airport code mapping
            dest_code = airport_codes.get(destination, destination)
            route_key = f"{origin}-{dest_code}"
        
        available_flights = flights.get(route_key, [
            {'airline': 'Generic Air', 'flight': 'GA001', 'price': 400, 'departure': '12:00', 'arrival': '15:30'}
        ])
        
        # Calculate total cost for all travelers and filter by budget
        budget_per_person = budget / travelers if travelers > 0 else budget
        affordable_flights = []
        
        for flight in available_flights:
            total_cost = flight['price'] * travelers
            if flight['price'] <= budget_per_person:
                flight_copy = flight.copy()
                flight_copy['total_cost'] = total_cost
                flight_copy['cost_per_person'] = flight['price']
                affordable_flights.append(flight_copy)
        
        # Add airline preferences
        for flight in affordable_flights:
            airline_info = airlines.get(flight['airline'], {})
            flight['airline_rating'] = airline_info.get('rating', 3.5)
            flight['preference_reason'] = f"{airline_info.get('preference', 'standard')} option"
        
        # Determine recommended flight (prefer Delta if within budget, otherwise cheapest)
        recommended_flight = None
        if affordable_flights:
            delta_flights = [f for f in affordable_flights if f['airline'] == 'Delta']
            if delta_flights:
                recommended_flight = delta_flights[0]
                recommended_flight['reason'] = 'Preferred airline match'
            else:
                recommended_flight = min(affordable_flights, key=lambda x: x['price'])
                recommended_flight['reason'] = 'Best value option'
        
        result = {
            'route': f"{origin} → {destination}",
            'travel_date': travel_date,
            'flights_found': len(affordable_flights),
            'available_flights': affordable_flights,
            'recommended_flight': recommended_flight,
            'budget_per_person': budget_per_person,
            'total_budget': budget,
            'travelers': travelers,
            'status': 'success' if affordable_flights else 'no_flights_in_budget'
        }
        
        print(f"[tools] bookingID={self.booking_id} search_flights <- flights_found={len(affordable_flights)}, status={result['status']}")
        return result
    
    @tool(name="publish_event", context=True)
    def publish_event(self, event_type: str, event_data: Dict[str, Any], tool_context: ToolContext) -> Dict[str, Any]:
        """Publish flight search events"""
        try:
            print(f"[tools] bookingID={self.booking_id} publish_event -> event_type={event_type}")
            
            response = eventbridge.put_events(
                Entries=[{
                    'Source': 'workshop.flight-manager-agent',
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
    budget = detail.get('budget', 600)
    travelers = detail.get('travelers', 2)
    
    print(f"[event] bookingID={booking_id} flight search requested for {origin} → {destination} on {travel_date}")
    
    # Create S3 session manager
    session_manager = S3SessionManager(
        session_id=booking_id,
        bucket=SESSION_BUCKET,
        prefix="flight-sessions",
        region_name=AWS_REGION
    )
    
    # Create agent with session management and flight tools
    tools = FlightTools(booking_id, session_manager)
    model = BedrockModel(model_id="global.anthropic.claude-sonnet-4-6")
    agent = Agent(
        agent_id="flight-searcher",  # Consistent agent ID for session restoration
        name="flight-manager-agent",
        model=model,
        session_manager=session_manager,
        system_prompt="""You are a flight search agent for travel booking.

Search for available flights for the requested route and date using the search_flights tool.
Analyze the options and provide recommendations based on budget, airline preferences, and value.
Then publish a FlightSearchCompleted event with your findings using the publish_event tool.""",
        tools=[tools.search_flights, tools.publish_event]
    )
    
    # Process flight search request
    prompt = f"""
    Search for flights for booking:
    - Route: {origin} to {destination}
    - Travel Date: {travel_date}
    - Budget: ${budget} total for {travelers} travelers
    - Booking ID: {booking_id}
    
    1. Use search_flights tool to find available options
    2. Analyze flight options and provide recommendations
    3. Publish FlightSearchCompleted event with your search results
    """
    
    print("=" * 80)
    print(f"[FLIGHT MANAGER AGENT] bookingID={booking_id} - Agent Response START")
    print("=" * 80)
    response = agent(prompt)
    print()  # Line break after response
    print("=" * 80)
    print(f"[FLIGHT MANAGER AGENT] bookingID={booking_id} - Agent Response END")
    print("=" * 80)
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Flight search completed with session',
            'booking_id': booking_id,
            'status': 'search_completed',
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
        print(f"[event] bookingID={booking_id} flight manager agent received event")
        
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
        print(f"[event] bookingID=unknown flight manager agent error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'message': 'Flight manager agent error'
            })
        }