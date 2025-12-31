
# Movie Ticket Booking System

A command-line interface (CLI) based ticket booking application built with Python and SQLite, designed for managing movie screenings, seat bookings, cancellations, and reporting.

---

##  System Architecture

The system follows a layered architecture:

- **Client Layer**: CLI-based user interface
- **Controller Layer**: Handles user input and menu navigation
- **Service Layer**: Contains business logic (seat mapping, booking, cancellation)
- **Repository Layer**: SQLite database for data persistence
- **External Integrations**: Designed to be extended with payment gateways, user authentication, and cloud storage

---

##  Database Design

### Entity Relationship Diagram (ERD)
- A `Screen` can host multiple `Shows`
- A `Show` can have many `Tickets`
- A `Ticket` can contain multiple `TicketSeat`s
- Each `TicketSeat` is uniquely linked to a `Show` to prevent double booking

### Schema

#### `Screen`
| Field | Type      | Constraints  | Description          |
|-------|-----------|--------------|----------------------|
| id    | INTEGER   | PK, AI       | Auto-increment ID    |
| name  | TEXT      | NOT NULL     | Movie/Screen name    |
| rows  | INTEGER   | NOT NULL     | Number of seat rows  |
| cols  | INTEGER   | NOT NULL     | Number of seat columns |

#### `Show`
| Field      | Type    | Constraints     | Description          |
|------------|---------|-----------------|----------------------|
| id         | INTEGER | PK, AI          | Auto-increment ID    |
| screen_id  | INTEGER | FK → screen.id  | Reference to Screen  |
| show_ts    | TEXT    | NOT NULL        | Show date and time   |
| base_price | REAL    | NOT NULL        | Base ticket price    |

#### `Ticket`
| Field  | Type    | Constraints    | Description               |
|--------|---------|----------------|---------------------------|
| id     | INTEGER | PK, AI         | Auto-increment ID         |
| show_id| INTEGER | FK → show.id   | Reference to Show         |
| user   | TEXT    | NOT NULL       | Customer name             |
| mobile | TEXT    | 10-digit       | Customer mobile number    |
| status | TEXT    | NOT NULL       | `BOOKED` or `CANCELLED`   |
| total  | REAL    | NOT NULL       | Total price paid          |

#### `TicketSeat`
| Field    | Type    | Constraints                | Description               |
|----------|---------|----------------------------|---------------------------|
| id       | INTEGER | PK, AI                     | Auto-increment ID         |
| ticket_id| INTEGER | FK → ticket.id             | Reference to Ticket       |
| show_id  | INTEGER | FK → show.id               | Reference to Show         |
| row      | INTEGER | NOT NULL                   | Seat row                  |
| col      | INTEGER | NOT NULL                   | Seat column               |
| price    | REAL    | NOT NULL                   | Price for this seat       |
| UNIQUE(show_id, row, col) | Prevents double booking | |

---

##  Functional Flows

### 3.1 Booking a Ticket
1. Select **Book Tickets** from the menu
2. Choose a movie from the list
3. Select a date (7-day window)
4. Choose a show time (10 AM, 2 PM, 6 PM)
5. View seat map:
   - □ Available
   - ■ Booked
   - X Selected by user
6. Select seats (e.g., `A1,B2`)
7. Enter name and mobile number
8. Review booking summary and confirm
9. Ticket is created and stored in the database

### 3.2 Cancelling Tickets
1. Select **Cancel Tickets**
2. Choose movie → date
3. Enter Booking ID (e.g., `B12`)
4. System validates and displays booked seats
5. Cancel options:
   - Single seat → partial refund
   - Multiple seats → partial refund
   - All seats → full cancellation

### 3.3 Reports
1. Select **Show Report**
2. Choose movie → date
3. View per-show details:
   - Occupancy (X/Y seats, Z%)
   - Revenue collected
   - Seat type breakdown (Standard, Premium)

---

##  Controllers & Functions

### BookingController
| Function     | Input                | Output         | Validation           |
|--------------|----------------------|----------------|----------------------|
| get_movies   | —                    | List of movies | DB not empty         |
| get_dates    | movie                | List of dates  | Movie exists         |
| get_shows    | movie, date          | List of shows  | Valid date           |
| book         | show_id, seats[], user, mobile | Ticket      | Seat availability    |
| cancel       | ticket_id, seats[]   | Refund         | Ticket must be BOOKED |
| report       | movie, date          | Report         | Valid movie/date     |

---

##  REST API Design (Future Extension)

| Method | URL                                | Purpose          | Body                                  | Response     |
|--------|------------------------------------|------------------|---------------------------------------|--------------|
| GET    | `/api/movies`                      | List movies      | —                                     | `[Movie]`    |
| GET    | `/api/movies/{name}/dates`         | Dates for movie  | —                                     | `[Date]`     |
| GET    | `/api/movies/{name}/shows?date=`   | Shows for date   | —                                     | `[Show]`     |
| POST   | `/api/tickets`                     | Book ticket      | `{user, mobile, show_id, seats[]}`    | `TicketDTO`  |
| PUT    | `/api/tickets/{id}/cancel`         | Cancel seats     | `{seats[]}`                           | `RefundDTO`  |
| GET    | `/api/reports/{movie}/{date}`      | Get report       | —                                     | `ReportDTO`  |

---

##  UI Wireframes (CLI Examples)

### Movie List
```
Movies:
1. Coolie
2. Thug Life
3. Love Marriage
B. Back
```

### Seat Selection
```
Seat Layout (□ Available, ■ Booked, X Yours)
  1 2 3 4 5 6 7
A □ □ ■ □ □ □ □
B □ □ □ ■ □ □ □
...
Select seats: A1,B2
```

### Booking Summary
```
Booking Confirmed!
Movie: Coolie
Date: 2025-09-04
Show: 6 PM
Seats:
A1 - Standard ₹100
B2 - Standard ₹100
Total: ₹200
Booking ID: B15
```

### Report Output
```
Show Reports for Coolie on 2025-09-04
---
Show Time   Occupancy       Revenue
10 AM       14/49 (28%)     ₹1800
2 PM        5/49 (10%)      ₹600

Seat Breakdown
Standard: 10 (₹1000), Premium: 4 (₹800)
Standard: 3 (₹300), Premium: 2 (₹300)
```

---

##  Future Enhancements
- Payment gateway integration
- User authentication and profiles
- Cloud storage for reports
- Web and mobile frontend using the REST API

---

##  Technologies Used
- **Backend**: Python
- **Database**: SQLite

This project is for educational and portfolio purposes.
