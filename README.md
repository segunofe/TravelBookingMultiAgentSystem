# Multi-Agent AI Architecture on AWS Serverless — Travel Booking

A serverless, event-driven multi-agent system built on **AWS Lambda**, **Amazon EventBridge**, **Amazon SQS**, and **AWS Step Functions**. The system automates a travel-booking workflow using a **Planner Agent**, **Weather Agent**, and **Flight Manager Agent**, with a human-in-the-loop step for high-risk bookings. 

Interesting! I successfully integrated the **Hotel Agent** to book an hotel for the trip, without disturbing the other agents.

<img width="1893" height="586" alt="image" src="https://github.com/user-attachments/assets/1f2f597c-67f9-4152-b6c7-28a96aab5498" />

Be


<img width="975" height="279" alt="image" src="https://github.com/user-attachments/assets/fee9eb86-c32d-4ddf-a405-93e16b509614" />


## Why Asynchronous, Event-Driven Agents?

Synchronous agent interactions are simple to prototype but break down once agents need real time to reason, call external APIs, process complex chains, or wait on human approval — serverless compute can't afford to sit idle burning execution time against timeout limits. This project instead uses **asynchronous coordination**, implemented two ways:

- **Choreography** (primary focus of this repo) — agents communicate through events on a custom **Amazon EventBridge** bus, invoking **AWS Lambda** functions. Emphasizes loose coupling and flexibility; each agent reacts independently to the events it cares about.
- **Orchestration** — a central controller coordinates the same agents using **AWS Step Functions** and a **State Machine**, emphasizing visibility, control, and centralized state management.

Both patterns were implemented in this project. The bulk of this README covers the **Choreography** implementation; the Orchestration variant is included as an alternative pattern (see below) but isn't detailed step-by-step here.

## Architecture

```
TravelRequestSubmitted
        │
        ▼
   Planner Agent  ──emits──▶ DatesFinalized
        │                         │
        │              ┌──────────┴──────────┐
        │              ▼                     ▼
        │        Weather Agent         Flight Manager Agent
        │              │                     │
        │   WeatherAnalysisCompleted   FlightSearchCompleted
        │              └──────────┬──────────┘
        │                         ▼
        └───────────────▶  Planner Agent (decision)
                                 │
                    ┌────────────┴────────────┐
                    ▼                          ▼
             Auto-approve              HumanReviewRequired
                                              │
                                              ▼
                                        Amazon SQS queue
                                              │
                                              ▼
                                   Human decision → HumanApprovalDecision
                                              │
                                              ▼
                                        Planner Agent
                                (finalizes or cancels booking)
```

All events flow through a custom EventBridge bus, and a catch-all rule streams every event to CloudWatch Logs for a full audit trail.

---

## Module 1 — Set Up Amazon EventBridge for Multi-Agent Communication

Resources already provisioned by CloudFormation: the custom event bus, the three Lambda functions (Planner, Weather, Flight Manager), and the SQS queue. This module wires them together with EventBridge rules and permissions.

![Deploy the Lambda function and pull stack resources](screenshots/deploy-hotel-agent-lambda.png)

### Steps performed

1. **Set environment variables** — region, account ID, stack name, and pulled the event bus name and Lambda ARNs from the CloudFormation stack outputs.
2. **`InitialTravelRequestRule`** — routes `TravelRequestSubmitted` events (source `workshop.travel-request`) to the **Planner Agent**, kicking off the booking workflow.
3. **`PlannerDatesRule`** — routes `DatesFinalized` events (source `workshop.planner-agent`) to **both** the Weather and Flight Manager agents simultaneously, enabling parallel fan-out processing.
4. **`WeatherCompletedRule`** and **`FlightCompletedRule`** — route each agent's completion event (`WeatherAnalysisCompleted`, `FlightSearchCompleted`) back to the Planner, which needs both results to make a decision.
5. **Lambda permissions** — granted `events.amazonaws.com` explicit `lambda:InvokeFunction` permission for every rule, scoped to that rule's ARN. Without this step, rules fire but invocations fail silently.
6. **Human-in-the-loop path** — created an SQS queue (`multi-agent-human-review`), a `HumanReviewRule` that routes `HumanReviewRequired` events from the Planner to that queue, and the SQS resource policy allowing EventBridge to send messages.
7. **`HumanApprovalRule`** — routes `HumanApprovalDecision` events (source `workshop.human-review`) back to the Planner to close the loop after a human approves or rejects a booking.
8. **`CatchAllEventsRule`** — captures every event from all five sources and streams them to a CloudWatch Logs group (`/aws/events/multi-agent-workshop`) for observability and debugging.

<img width="1866" height="836" alt="image" src="https://github.com/user-attachments/assets/2dc6f111-b4e5-4060-b755-63745154df9f" />

<img width="975" height="434" alt="image" src="https://github.com/user-attachments/assets/a782cb0a-e782-4961-bdc0-b0807fadf448" />

### Event Pattern 
<img width="975" height="404" alt="image" src="https://github.com/user-attachments/assets/c43f4e73-1696-4a36-8b9a-64acbbd658be" />

### Event target 

<img width="975" height="408" alt="image" src="https://github.com/user-attachments/assets/bbf59c3b-0409-4b70-b8f1-a5547d3b3b03" />





### Rules created

| Rule | Source → Detail-Type | Target |
|---|---|---|
| `InitialTravelRequestRule` | `workshop.travel-request` → `TravelRequestSubmitted` | Planner Agent |
| `PlannerDatesRule` | `workshop.planner-agent` → `DatesFinalized` | Weather Agent + Flight Manager Agent |
| `WeatherCompletedRule` | `workshop.weather-agent` → `WeatherAnalysisCompleted` | Planner Agent |
| `FlightCompletedRule` | `workshop.flight-manager-agent` → `FlightSearchCompleted` | Planner Agent |
| `HumanReviewRule` | `workshop.planner-agent` → `HumanReviewRequired` | SQS queue |
| `HumanApprovalRule` | `workshop.human-review` → `HumanApprovalDecision` | Planner Agent |
| `CatchAllEventsRule` | all five sources | CloudWatch Logs |

---
### Add permission for events

<img width="975" height="524" alt="image" src="https://github.com/user-attachments/assets/82c80e3c-24a7-461a-9612-81e4624cdafe" />


## Module 2 — Test the Multi-Agent Choreography Flow

With the rules in place, a test travel request event was published to observe the full choreography end-to-end.

### Test scenario

A high-risk booking was sent: `LAX → Miami`, budget `$1000`, 2 travelers, deliberately chosen to trigger a weather-risk escalation.

<img width="975" height="330" alt="image" src="https://github.com/user-attachments/assets/f79700c4-38a0-4640-a62d-7a3bc42c695b" />


### Observed event sequence (via CloudWatch Logs Insights)

| Order | Source | Event Type | Description |
|---|---|---|---|
| 1 | `workshop.planner-agent` | `DatesFinalized` | Planner extracts and publishes trip details |
| 2 | `workshop.weather-agent` | `WeatherAnalysisCompleted` | Weather analysis finishes |
| 3 | `workshop.flight-manager-agent` | `FlightSearchCompleted` | Flight search finishes |
| 4 | `workshop.planner-agent` | `HumanReviewRequired` | High-risk scenario detected (severe weather) |

The Weather and Flight events landed close together in time, confirming the two agents ran **in parallel** off the same `DatesFinalized` event.

### What was verified

- **Event sequencing** via a CloudWatch Logs Insights query parsing `source`, `detail-type`, and `bookingID` from the catch-all log group.
- **Agent reasoning** by tailing the Planner Lambda's own logs — showing its step-by-step tool calls (`extract_travel_details`, `publish_event`) and the events it emitted.
- **Human-in-the-loop queue** — confirmed the `HumanReviewRequired` message landed in the SQS queue with the full booking and risk payload.
- **Closing the loop** — sent a simulated `HumanApprovalDecision` event (`approved`) back through EventBridge and confirmed the Planner picked it up and finalized the booking.

### CloudWatch Log insights

<img width="975" height="470" alt="image" src="https://github.com/user-attachments/assets/dd04f919-f189-42c2-9eb1-9c2b80c47a6a" />

### After human approval 

<img width="975" height="207" alt="image" src="https://github.com/user-attachments/assets/361e3578-dda5-4e20-9496-d3dde844e79e" />




---

## Orchestration Method (AWS Step Functions)

In addition to the Choreography pattern above, an **Orchestration** version of the same workflow was implemented using an **AWS Step Functions state machine** (`travel-booking-orchestration`) as a central controller. Instead of agents reacting to events on an EventBridge bus, the state machine directly invokes each Lambda function as a step, runs the weather and flight lookups in a **Parallel** state, branches on the Planner's decision, and — for high-risk bookings — pauses in a `WaitForHuman` state until a human decision resumes the execution.

![Step Functions orchestration graph for the travel booking workflow](screenshots/step-functions-orchestration-graph.png)

This gives the same end-to-end capability as the choreography flow, but with centralized visibility and built-in state management via the Step Functions console, rather than distributed event rules. (Not covered in detail here — see the Choreography sections above for the full step-by-step build.)

### Before Human Approval 

<img width="975" height="670" alt="image" src="https://github.com/user-attachments/assets/28314180-db5c-4d11-b58c-0ac366ece1db" />

### After Approval 

<img width="975" height="636" alt="image" src="https://github.com/user-attachments/assets/9e1a0c37-3b4a-466f-b9a4-c0802eda2a53" />

### SNS Topic Creation and Notification via Email 

<img width="975" height="704" alt="image" src="https://github.com/user-attachments/assets/e1055939-d146-488e-940f-c9d31122334e" />
<img width="975" height="497" alt="image" src="https://github.com/user-attachments/assets/a6e05284-d80b-4ef5-8b3e-3815f04ab35a" />

<img width="975" height="402" alt="image" src="https://github.com/user-attachments/assets/41b875b1-f6e1-4162-92cf-529e8a57eaa4" />

### Email received after the hotel agent has booked an hotel 

<img width="1462" height="752" alt="image" src="https://github.com/user-attachments/assets/d8bc6fe8-0e35-4ad7-8612-0a5e95affbe6" />







---

## Key Takeaways

- Event-driven **choreography** lets agents work independently and in parallel while staying coordinated through shared events on an EventBridge bus.
- Explicit Lambda permissions are required per rule — EventBridge rules alone don't grant invoke access.
- SQS + EventBridge enables a clean **human-in-the-loop** pattern for high-risk decisions without blocking the rest of the system.
- A catch-all EventBridge rule feeding CloudWatch Logs gives a simple, centralized audit trail across all agents.
- The same workflow can alternatively be run as a **Step Functions orchestration** for centralized control and visibility, trading loose coupling for a single source of truth on workflow state.
