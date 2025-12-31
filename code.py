import sqlite3
import threading
from datetime import datetime, timedelta
from contextlib import contextmanager
import re

class Screen:
    def __init__(self, id, name, rows, cols):
        self.id = id
        self.name = name
        self.rows = rows
        self.cols = cols

class Show:
    def __init__(self, id, screen_id, show_ts, base_price):
        self.id = id
        self.screen_id = screen_id
        self.show_ts = show_ts
        self.base_price = base_price

class Ticket:
    def __init__(self, id, show_id, user, mobile, status, total):
        self.id = id
        self.show_id = show_id
        self.user = user
        self.mobile = mobile
        self.status = status
        self.total = total

class TicketSeat:
    def __init__(self, id, ticket_id, show_id, row, col, price):
        self.id = id
        self.ticket_id = ticket_id
        self.show_id = show_id
        self.row = row
        self.col = col
        self.price = price

class SeatMapService:
    def __init__(self, db_connection):
        self.db = db_connection
        self.locks = {}  # Show-level locks
    
    def get_lock(self, show_id):
        if show_id not in self.locks:
            self.locks[show_id] = threading.Lock()
        return self.locks[show_id]
    
    def get_price(self, row):
        """Get price based on seat row (A-C = Standard, D-G = Premium)"""
        return 100 if row in [0, 1, 2] else 150  # 0=A, 1=B, 2=C are Standard (₹100), others are Premium (₹150)
    
    def get_seat_type(self, row):
        """Get seat type based on row"""
        return "Standard" if row in [0, 1, 2] else "Premium"  # A, B, C = Standard, D, E, F, G = Premium
    
    def build_seat_map(self, show_id, rows, cols):
        """Build 2D seat map from ticket_seat rows"""
        seat_map = [[True for _ in range(cols)] for _ in range(rows)]  # True = available
        
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT ts.row, ts.col 
            FROM ticket_seat ts 
            JOIN ticket t ON ts.ticket_id = t.id 
            WHERE ts.show_id = ? AND t.status = 'BOOKED'
        """, (show_id,))
        
        for row, col in cursor.fetchall():
            if 0 <= row < rows and 0 <= col < cols:
                seat_map[row][col] = False  # False = occupied
        
        return seat_map
    
    def show_seat_map(self, show_id, rows, cols, user_seats=None):
        """Display 2D seat map with user seats highlighted and seat types/prices"""
        seat_map = self.build_seat_map(show_id, rows, cols)
        print("\nSeat Layout:")
        print("□ = Available  ■ = Booked  X = Your Booking")
        print("-" * (cols * 8 + 15))
        
        # Print column headers
        print("    ", end="")
        for col in range(cols):
            print(f"{col+1:2d}     ", end="")
        print()
        
        # Print rows with letters and seat types/prices
        for row in range(rows):
            print(f"{chr(65+row)}   ", end="")
            for col in range(cols):
                if user_seats and (row, col) in user_seats:
                    mark = "X"
                elif seat_map[row][col]:
                    mark = "□"
                else:
                    mark = "■"
                
                seat_type = "S" if self.get_seat_type(row) == "Standard" else "P"
                print(f" {mark}({seat_type}) ", end="")
            print()
        
        # Print seat type legend
        print("\nSeat Types:")
        print("S = Standard (₹100) - Rows A, B, C")
        print("P = Premium (₹150) - Rows D, E, F, G")

class BookingService:
    def __init__(self, db_connection, seat_map_service):
        self.db = db_connection
        self.seat_map_service = seat_map_service
    
    @contextmanager
    def transaction(self):
        cursor = self.db.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            yield cursor
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise e
    
    def is_seat_available(self, show_id, row, col):
        """Check if a specific seat is available"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT 1 FROM ticket_seat ts 
            JOIN ticket t ON ts.ticket_id = t.id 
            WHERE ts.show_id = ? AND ts.row = ? AND ts.col = ? AND t.status = 'BOOKED'
        """, (show_id, row, col))
        return cursor.fetchone() is None
    
    def recheck_seats(self, show_id, seats):
        """Re-verify seat availability before booking"""
        for row, col in seats:
            if not self.is_seat_available(show_id, row, col):
                return False, (row, col)
        return True, None
    
    def book_seats(self, show_id, user_name, user_mobile, seats, rows, cols):
        """Atomic multi-seat reservation"""
        if not seats:
            raise ValueError("No seats provided for booking")
        
        # Validate all seats are free and calculate total price
        total_price = 0
        seat_details = []
        
        for row, col in seats:
            if not self.is_seat_available(show_id, row, col):
                raise ValueError(f"Seat {chr(65+row)}{col+1} is already booked")
            
            price = self.seat_map_service.get_price(row)
            total_price += price
            seat_details.append((row, col, price))
        
        lock = self.seat_map_service.get_lock(show_id)
        
        with lock:  # Acquire show-level lock
            with self.transaction() as cursor:  # Begin immediate transaction
                # Re-check seat availability within transaction
                is_available, occupied_seat = self.recheck_seats(show_id, seats)
                if not is_available:
                    row, col = occupied_seat
                    raise ValueError(f"Seat {chr(65+row)}{col+1} became unavailable during booking")
                
                # Insert ticket
                cursor.execute("""
                    INSERT INTO ticket (show_id, user, mobile, status, total) 
                    VALUES (?, ?, ?, 'BOOKED', ?)
                """, (show_id, user_name, user_mobile, total_price))
                
                ticket_id = cursor.lastrowid
                
                # Insert ticket seats
                for row, col, price in seat_details:
                    cursor.execute("""
                        INSERT INTO ticket_seat (ticket_id, show_id, row, col, price) 
                        VALUES (?, ?, ?, ?, ?)
                    """, (ticket_id, show_id, row, col, price))
                
                return ticket_id, total_price, seat_details
    
    def cancel_seats(self, ticket_id, seats_to_cancel):
        """Cancel specific seats in a booking"""
        with self.transaction() as cursor:
            # Check if ticket exists and is booked
            cursor.execute("""
                SELECT t.total, t.show_id FROM ticket t
                WHERE t.id = ? AND t.status = 'BOOKED'
            """, (ticket_id,))
            
            result = cursor.fetchone()
            if not result:
                raise ValueError("Ticket not found or not in BOOKED status")
            
            total_amount, show_id = result
            refund_amount = 0
            
            # Calculate refund amount based on seat prices
            for row, col in seats_to_cancel:
                cursor.execute("""
                    SELECT price FROM ticket_seat 
                    WHERE ticket_id = ? AND row = ? AND col = ?
                """, (ticket_id, row, col))
                price_result = cursor.fetchone()
                if price_result:
                    refund_amount += price_result[0]
            
            # Delete specific seats
            for row, col in seats_to_cancel:
                cursor.execute("""
                    DELETE FROM ticket_seat 
                    WHERE ticket_id = ? AND row = ? AND col = ?
                """, (ticket_id, row, col))
            
            # Check if any seats remain
            cursor.execute("""
                SELECT COUNT(*) FROM ticket_seat WHERE ticket_id = ?
            """, (ticket_id,))
            
            remaining_seats = cursor.fetchone()[0]
            
            if remaining_seats == 0:
                # All seats cancelled, update ticket status
                cursor.execute("""
                    UPDATE ticket SET status = 'CANCELLED', total = 0 WHERE id = ?
                """, (ticket_id,))
            else:
                # Partial cancellation, update total
                new_total = total_amount - refund_amount
                cursor.execute("""
                    UPDATE ticket SET total = ? WHERE id = ?
                """, (new_total, ticket_id))
            
            return refund_amount
    
    def get_user_seats(self, ticket_id):
        """Get seats for a specific ticket"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT row, col FROM ticket_seat WHERE ticket_id = ?
        """, (ticket_id,))
        return cursor.fetchall()

class MovieTicketingSystem:
    def __init__(self, db_path=":memory:"):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.init_database()
        self.seat_map_service = SeatMapService(self.db)
        self.booking_service = BookingService(self.db, self.seat_map_service)
        self.populate_sample_data()
    
    def init_database(self):
        """Initialize database schema"""
        cursor = self.db.cursor()
        
        # Create tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS screen (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                rows INTEGER NOT NULL,
                cols INTEGER NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS show (
                id INTEGER PRIMARY KEY,
                screen_id INTEGER NOT NULL,
                show_ts TEXT NOT NULL,
                base_price REAL NOT NULL,
                FOREIGN KEY (screen_id) REFERENCES screen (id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ticket (
                id INTEGER PRIMARY KEY,
                show_id INTEGER NOT NULL,
                user TEXT NOT NULL,
                mobile TEXT,
                status TEXT NOT NULL,
                total REAL NOT NULL,
                FOREIGN KEY (show_id) REFERENCES show (id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ticket_seat (
                id INTEGER PRIMARY KEY,
                ticket_id INTEGER NOT NULL,
                show_id INTEGER NOT NULL,
                row INTEGER NOT NULL,
                col INTEGER NOT NULL,
                price REAL NOT NULL,
                UNIQUE(show_id, row, col),
                FOREIGN KEY (ticket_id) REFERENCES ticket (id),
                FOREIGN KEY (show_id) REFERENCES show (id)
            )
        """)
        
        self.db.commit()
    
    def format_time(self, time_str):
        """Convert 24-hour time to 12-hour format with AM/PM"""
        try:
            hour, minute, second = map(int, time_str.split(':'))
            if hour == 0:
                return "12 AM"
            elif hour < 12:
                return f"{hour} AM"
            elif hour == 12:
                return "12 PM"
            else:
                return f"{hour - 12} PM"
        except:
            return time_str
    
    def populate_sample_data(self):
        """Populate sample data"""
        cursor = self.db.cursor()
        
        # Insert screens with 7 columns (1-7) and 7 rows (A-G)
        cursor.execute("INSERT OR IGNORE INTO screen (id, name, rows, cols) VALUES (1, 'Coolie', 7, 7)")
        cursor.execute("INSERT OR IGNORE INTO screen (id, name, rows, cols) VALUES (2, 'Thug Life', 7, 7)")
        cursor.execute("INSERT OR IGNORE INTO screen (id, name, rows, cols) VALUES (3, 'Love Marriage', 7, 7)")
        
        # Insert shows for next 7 days
        base_date = datetime.now()
        show_id = 1
        for i in range(7):
            show_date = base_date + timedelta(days=i)
            for movie_id in [1, 2, 3]:
                for show_time in ["10:00:00", "14:00:00", "18:00:00"]:
                    show_ts = show_date.strftime(f"%Y-%m-%d {show_time}")
                    price = 150.0 if movie_id == 1 else 250.0
                    cursor.execute("""
                        INSERT OR IGNORE INTO show (id, screen_id, show_ts, base_price) 
                        VALUES (?, ?, ?, ?)
                    """, (show_id, movie_id, show_ts, price))
                    show_id += 1
        
        self.db.commit()
    
    def get_movies(self):
        """Get all movies (distinct show names)"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT DISTINCT s.name 
            FROM show sh
            JOIN screen s ON sh.screen_id = s.id
            ORDER BY s.name
        """)
        return [row[0] for row in cursor.fetchall()]
    
    def get_dates_for_movie(self, movie_name):
        """Get all dates for a specific movie"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT DISTINCT DATE(sh.show_ts) as show_date
            FROM show sh
            JOIN screen s ON sh.screen_id = s.id
            WHERE s.name = ?
            ORDER BY show_date
        """, (movie_name,))
        return [row[0] for row in cursor.fetchall()]
    
    def get_shows_for_movie_and_date(self, movie_name, date):
        """Get all shows for a specific movie and date"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT sh.id, sh.show_ts, sh.base_price, s.rows, s.cols
            FROM show sh
            JOIN screen s ON sh.screen_id = s.id
            WHERE s.name = ? AND DATE(sh.show_ts) = ?
            ORDER BY sh.show_ts
        """, (movie_name, date))
        return cursor.fetchall()
    
    def get_show_details(self, show_id):
        """Get detailed show information"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT sh.id, sh.show_ts, sh.base_price, s.name, s.rows, s.cols
            FROM show sh
            JOIN screen s ON sh.screen_id = s.id
            WHERE sh.id = ?
        """, (show_id,))
        return cursor.fetchone()
    
    def get_ticket_details(self, ticket_id):
        """Get detailed ticket information"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT t.id, t.user, t.mobile, t.status, t.total, s.name, sh.show_ts, sh.id as show_id
            FROM ticket t
            JOIN show sh ON t.show_id = sh.id
            JOIN screen s ON sh.screen_id = s.id
            WHERE t.id = ?
        """, (ticket_id,))
        return cursor.fetchone()
    
    def get_seats_for_ticket(self, ticket_id):
        """Get seats for a specific ticket"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT row, col FROM ticket_seat WHERE ticket_id = ? ORDER BY row, col
        """, (ticket_id,))
        return cursor.fetchall()
    
    def menu_select(self, title, options, allow_back=True):
        """Generic menu selection function"""
        while True:
            print(f"\n{title}")
            for i, option in enumerate(options, 1):
                print(f"{i}. {option}")
            if allow_back:
                print("B. Back")
            
            choice = input("Enter choice: ").strip()
            
            if allow_back and choice.upper() == "B":
                return None
            
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                return int(choice), options[int(choice) - 1]
            
            print("Invalid choice! Please try again.")
    
    def book_tickets(self):
        """Book tickets interface"""
        try:
            # Select movie
            movies = self.get_movies()
            if not movies:
                print("No movies available!")
                input("Press Enter to continue...")
                return
            
            result = self.menu_select("Select Movie", movies)
            if result is None:
                return
            movie_index, movie = result
            
            # Select date
            dates = self.get_dates_for_movie(movie)
            if not dates:
                print(f"No shows available for {movie}!")
                input("Press Enter to continue...")
                return
            
            result = self.menu_select(f"{movie} - Select Day", dates)
            if result is None:
                return
            date_index, date = result
            
            # Select show
            shows = self.get_shows_for_movie_and_date(movie, date)
            if not shows:
                print(f"No shows available for {movie} on {date}!")
                input("Press Enter to continue...")
                return
            
            # Format show times to 12-hour format
            show_options = []
            for show in shows:
                time_part = show[1].split()[1]  # Extract time part
                formatted_time = self.format_time(time_part)
                show_options.append(formatted_time)
            
            result = self.menu_select(f"{movie} - {date} - Select Show", show_options)
            if result is None:
                return
            show_index, show_time = result
            
            # Find the selected show details
            selected_show = shows[show_index - 1]
            show_id, show_time_full, base_price, rows, cols = selected_show
            
            # Show seat map
            self.seat_map_service.show_seat_map(show_id, rows, cols)
            
            # Get seat selection
            while True:
                print(f"\nEnter seats to book (comma separated, e.g., A1,B2,C3):")
                seat_input = input("Seats (or 'B' to go back): ").strip()
                
                if seat_input.upper() == 'B':
                    return
                
                if not seat_input:
                    print("Please enter at least one seat!")
                    continue
                
                seats = []
                seat_strings = seat_input.split(',')
                valid = True
                
                for seat_str in seat_strings:
                    seat_str = seat_str.strip().upper()
                    if len(seat_str) < 2:
                        print(f"Invalid seat format: {seat_str}")
                        valid = False
                        break
                    
                    row_char = seat_str[0]
                    if not row_char.isalpha() or ord(row_char) < 65 or ord(row_char) >= 65 + rows:
                        print(f"Invalid row: {row_char}")
                        valid = False
                        break
                    
                    row = ord(row_char) - 65
                    try:
                        col = int(seat_str[1:]) - 1
                        if col < 0 or col >= cols:
                            print(f"Invalid column: {seat_str[1:]}")
                            valid = False
                            break
                    except ValueError:
                        print(f"Invalid column: {seat_str[1:]}")
                        valid = False
                        break
                    
                    seats.append((row, col))
                
                if valid and seats:
                    # Check if all seats are available
                    unavailable_seats = []
                    for row, col in seats:
                        if not self.booking_service.is_seat_available(show_id, row, col):
                            unavailable_seats.append(f'{chr(65+row)}{col+1}')
                    
                    if unavailable_seats:
                        print(f"Following seats are not available: {', '.join(unavailable_seats)}")
                        continue
                    break
                elif not valid:
                    continue
                else:
                    print("No valid seats provided!")
            
            # Get user info
            while True:
                user_name = input("Enter your name: ").strip()
                if user_name:
                    break
                print("Name cannot be empty!")
            
            while True:
                user_mobile = input("Enter your 10-digit mobile number: ").strip()
                if re.match(r'^\d{10}$', user_mobile):
                    break
                print("Invalid mobile number! Please enter a 10-digit number.")
            
            # Show booking summary with seat types and prices
            seat_labels = []
            total_price = 0
            seat_details = []
            
            for row, col in seats:
                seat_type = self.seat_map_service.get_seat_type(row)
                price = self.seat_map_service.get_price(row)
                seat_label = f'{chr(65+row)}{col+1}({seat_type}:₹{price})'
                seat_labels.append(seat_label)
                total_price += price
                seat_details.append((row, col, seat_type, price))
            
            print(f"\nBooking Summary:")
            for detail in seat_details:
                row, col, seat_type, price = detail
                print(f"  {chr(65+row)}{col+1} - {seat_type} Seat: ₹{price}")
            print(f"Total Price: ₹{total_price}")
            
            confirm = input("Confirm booking? (y/n): ").strip().lower()
            if confirm != 'y':
                print("Booking cancelled.")
                input("Press Enter to continue...")
                return
            
            # Book seats
            try:
                ticket_id, total_price, booked_seats = self.booking_service.book_seats(
                    show_id, user_name, user_mobile, seats, rows, cols
                )
                print(f"\n-------------------------")
                print("Booking confirmed!")
                print(f"Movie: {movie}")
                print(f"Date: {date}")
                print(f"Show: {show_time}")
                print("Booked Seats:")
                for row, col, price in booked_seats:
                    seat_type = self.seat_map_service.get_seat_type(row)
                    print(f"  {chr(65+row)}{col+1} - {seat_type} Seat: ₹{price}")
                print(f"Total Price: ₹{total_price}")
                print(f"Booking ID: B{ticket_id}")
                print("-------------------------")
                input("\nPress Enter to return to Main Menu...")
            except ValueError as e:
                print(f"Booking failed: {e}")
                input("Press Enter to continue...")
            except Exception as e:
                print(f"Unexpected error during booking: {e}")
                input("Press Enter to continue...")
        
        except Exception as e:
            print(f"Error during booking process: {e}")
            input("Press Enter to continue...")
    
    def cancel_tickets(self):
        """Cancel tickets interface"""
        try:
            # Select movie
            movies = self.get_movies()
            if not movies:
                print("No movies available!")
                input("Press Enter to continue...")
                return
            
            result = self.menu_select("Select Movie for Cancellation", movies)
            if result is None:
                return
            movie_index, movie = result
            
            # Select date
            dates = self.get_dates_for_movie(movie)
            if not dates:
                print(f"No shows available for {movie}!")
                input("Press Enter to continue...")
                return
            
            result = self.menu_select(f"{movie} - Select Day", dates)
            if result is None:
                return
            date_index, date = result
            
            # Get booking ID
            while True:
                booking_id_input = input("Enter your Booking ID (or 'B' to go back): ").strip()
                if booking_id_input.upper() == 'B':
                    return
                
                if booking_id_input.startswith('B') and booking_id_input[1:].isdigit():
                    ticket_id = int(booking_id_input[1:])
                    break
                else:
                    print("Invalid Booking ID format! It should start with 'B' followed by numbers.")
            
            # Get ticket details
            ticket_details = self.get_ticket_details(ticket_id)
            if not ticket_details:
                print("Booking ID not found!")
                input("Press Enter to continue...")
                return
            
            ticket_id, user_name, user_mobile, status, total, screen_name, show_time_full, show_id = ticket_details
            
            # Verify ticket matches selected movie and date
            if screen_name != movie:
                print(f"Booking does not match the selected movie! Booking is for {screen_name}")
                input("Press Enter to continue...")
                return
            
            ticket_date = show_time_full.split()[0]
            if ticket_date != date:
                print(f"Booking does not match the selected date! Booking is for {ticket_date}")
                input("Press Enter to continue...")
                return
            
            if status != 'BOOKED':
                print(f"Booking is not in BOOKED status! Current status: {status}")
                input("Press Enter to continue...")
                return
            
            # Get seat details
            seats = self.get_seats_for_ticket(ticket_id)
            seat_list = []
            for r, c in seats:
                seat_type = self.seat_map_service.get_seat_type(r)
                price = self.seat_map_service.get_price(r)
                seat_list.append(f'{chr(65+r)}{c+1}({seat_type}:₹{price})')
            
            # Parse show time and format it
            show_time_part = show_time_full.split()[1]
            show_time = self.format_time(show_time_part)
            
            # Get show details for price calculation
            show_details = self.get_show_details(show_id)
            if show_details:
                _, _, base_price, _, rows, cols = show_details
            else:
                base_price = 150  # Default price
                rows, cols = 7, 7  # Default dimensions for A-G and 1-7
            
            # If only one seat, direct cancellation
            if len(seats) == 1:
                row, col = seats[0]
                seat_type = self.seat_map_service.get_seat_type(row)
                price = self.seat_map_service.get_price(row)
                seat_label = f'{chr(65+row)}{col+1}({seat_type}:₹{price})'
                
                confirm = input(f"\nCancel booking for seat {seat_label}? Refund: ₹{price} (y/n/B to go back): ").strip().lower()
                
                if confirm.upper() == 'B':
                    return
                elif confirm == 'y':
                    try:
                        refund = self.booking_service.cancel_seats(ticket_id, [(row, col)])
                        print(f"Seat {chr(65+row)}{col+1} cancelled successfully!")
                        print(f"Refund processed: ₹{refund}")
                        input("\nPress Enter to return to Main Menu...")
                    except ValueError as e:
                        print(f"Cancellation failed: {e}")
                        input("Press Enter to continue...")
                else:
                    print("Cancellation aborted.")
                    input("Press Enter to continue...")
                return
            
            # For multiple seats, show seat map and allow selection
            user_seats = [(r, c) for r, c in seats]
            print(f"\nShow: {show_time}")
            print("Your booked seats (shown as X):")
            self.seat_map_service.show_seat_map(show_id, rows, cols, user_seats)
            
            while True:
                print(f"\nEnter seats to cancel (comma separated), 'ALL' to cancel all, or 'B' to go back:")
                print(f"Your seats: {', '.join(seat_list)}")
                cancel_input = input("Seats: ").strip().upper()
                
                if cancel_input == 'B':
                    return
                
                if cancel_input == 'ALL':
                    seats_to_cancel = seats
                    break
                
                # Parse input seats
                cancel_seats = []
                seat_strings = cancel_input.split(',')
                valid = True
                
                for seat_str in seat_strings:
                    seat_str = seat_str.strip()
                    if len(seat_str) < 2:
                        print(f"Invalid seat format: {seat_str}")
                        valid = False
                        break
                    
                    row_char = seat_str[0]
                    if not row_char.isalpha() or ord(row_char) < 65 or ord(row_char) >= 65 + rows:
                        print(f"Invalid row: {row_char}")
                        valid = False
                        break
                    
                    row = ord(row_char) - 65
                    try:
                        col = int(seat_str[1:]) - 1
                        if col < 0 or col >= cols:
                            print(f"Invalid column: {seat_str[1:]}")
                            valid = False
                            break
                    except ValueError:
                        print(f"Invalid column: {seat_str[1:]}")
                        valid = False
                        break
                    
                    if (row, col) not in [s for s in seats]:
                        print(f"Seat {seat_str} is not in your booking!")
                        valid = False
                        break
                    
                    cancel_seats.append((row, col))
                
                if valid and cancel_seats:
                    seats_to_cancel = cancel_seats
                    break
                elif not valid:
                    continue
                else:
                    print("No valid seats provided!")
            
            # Confirm cancellation with seat details
            seat_labels = []
            refund_amount = 0
            for row, col in seats_to_cancel:
                seat_type = self.seat_map_service.get_seat_type(row)
                price = self.seat_map_service.get_price(row)
                seat_labels.append(f'{chr(65+row)}{col+1}({seat_type}:₹{price})')
                refund_amount += price
            
            # Fixed the syntax error in the f-string
            seat_names = [label.split('(')[0] for label in seat_labels]
            confirm = input(f"\nCancel seats {', '.join(seat_names)}? Refund: ₹{refund_amount} (y/n/B to go back): ").strip().lower()
            
            if confirm.upper() == 'B':
                return
            elif confirm == 'y':
                try:
                    refund = self.booking_service.cancel_seats(ticket_id, seats_to_cancel)
                    print(f"Seats {', '.join(seat_names)} cancelled successfully!")
                    print(f"Refund processed: ₹{refund}")
                    input("\nPress Enter to return to Main Menu...")
                except ValueError as e:
                    print(f"Cancellation failed: {e}")
                    input("Press Enter to continue...")
            else:
                print("Cancellation aborted.")
                input("Press Enter to continue...")
        
        except Exception as e:
            print(f"Error during cancellation process: {e}")
            input("Press Enter to continue...")
    
    def show_report(self):
        """Show occupancy and revenue reports"""
        try:
            # Select movie
            movies = self.get_movies()
            if not movies:
                print("No movies available!")
                input("Press Enter to continue...")
                return
            
            result = self.menu_select("Select Movie for Report", movies)
            if result is None:
                return
            movie_index, movie = result
            
            # Select date
            dates = self.get_dates_for_movie(movie)
            if not dates:
                print(f"No shows available for {movie}!")
                input("Press Enter to continue...")
                return
            
            result = self.menu_select(f"{movie} - Select Day for Report", dates)
            if result is None:
                return
            date_index, date = result
            
            # Get shows for the selected movie and date
            shows = self.get_shows_for_movie_and_date(movie, date)
            if not shows:
                print(f"No shows available for {movie} on {date}!")
                input("Press Enter to continue...")
                return
            
            cursor = self.db.cursor()
            
            print(f"\n{'='*90}")
            print(f"Show Reports for {movie} on {date}")
            print(f"{'='*90}")
            print(f"{'Show Time':<15} {'Occupancy':<20} {'Revenue (₹)':<15} {'Seat Types Breakdown'}")
            print(f"{'-'*90}")
            
            for show in shows:
                show_id, show_time_full, base_price, rows, cols = show
                total_seats = rows * cols
                
                # Parse show time and format it
                show_time_part = show_time_full.split()[1]
                show_time = self.format_time(show_time_part)
                
                # Get booked seats and revenue for this show
                cursor.execute("""
                    SELECT 
                        COUNT(ts.id) as booked_seats,
                        COALESCE(SUM(ts.price), 0) as revenue
                    FROM ticket_seat ts
                    JOIN ticket t ON ts.ticket_id = t.id AND t.status = 'BOOKED'
                    WHERE ts.show_id = ?
                """, (show_id,))
                
                result = cursor.fetchone()
                booked_seats = result[0] if result[0] else 0
                revenue = result[1] if result[1] else 0
                
                # Calculate occupancy percentage
                occupancy_percent = (booked_seats / total_seats * 100) if total_seats > 0 else 0
                
                # Get seat type breakdown
                cursor.execute("""
                    SELECT 
                        CASE 
                            WHEN ts.row IN (0, 1, 2) THEN 'Standard'
                            ELSE 'Premium'
                        END as seat_type,
                        COUNT(*) as count,
                        SUM(ts.price) as type_revenue
                    FROM ticket_seat ts
                    JOIN ticket t ON ts.ticket_id = t.id AND t.status = 'BOOKED'
                    WHERE ts.show_id = ?
                    GROUP BY CASE 
                        WHEN ts.row IN (0, 1, 2) THEN 'Standard'
                        ELSE 'Premium'
                    END
                """, (show_id,))
                
                seat_breakdown = cursor.fetchall()
                breakdown_str = ""
                if seat_breakdown:
                    breakdown_parts = []
                    for seat_type, count, type_revenue in seat_breakdown:
                        breakdown_parts.append(f"{seat_type}: {count} seats (₹{type_revenue})")
                    breakdown_str = ", ".join(breakdown_parts)
                else:
                    breakdown_str = "No bookings"
                
                print(f"{show_time:<15} {booked_seats}/{total_seats} ({occupancy_percent:.1f}%) {'₹' + str(revenue):<15} {breakdown_str}")
            
            print(f"{'='*90}")
            input("\nPress Enter to continue...")
        
        except Exception as e:
            print(f"Error generating reports: {e}")
            input("Press Enter to continue...")
    
    def run(self):
        """Main application loop"""
        while True:
            print("\nMovie Ticket Booking System")
            print("1. Book Tickets")
            print("2. Cancel Tickets")
            print("3. Show Report")
            print("4. Exit")
            
            choice = input("Enter choice: ").strip()
            
            if choice == "1":
                self.book_tickets()
            elif choice == "2":
                self.cancel_tickets()
            elif choice == "3":
                self.show_report()
            elif choice == "4":
                print("Thank you for using the system!")
                break
            else:
                print("Invalid choice! Please try again.")

if __name__ == "__main__":
    # Create and run the system
    system = MovieTicketingSystem()
    system.run()