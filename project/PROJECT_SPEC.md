# Business Requirements & Project Specification (PROJECT_SPEC.md)

## 1. Project Overview & Scope

### 1.1 Business Identity
- **Business Name**: Bhagya Laxmi Library & PG (*Registered Trade Name*)
- **Application Purpose**: A high-performance, web-based study-seat / reading-room management and booking system designed specifically for the daily operations of **Bhagya Laxmi Library**.

> [!IMPORTANT]
> **Strict Non-Accommodation Scope**:
> The word "PG" is only a historical artifact of the business trade name. **No PG, hostel, room, bed, tenant, or accommodation features exist in this system.** The application deals exclusively with study seats in the air-conditioned reading library.

### 1.2 Core Constraints & Parameters
- **Seat Capacity**: Exactly **150 fixed study seats**, numbered sequentially from **1 to 150**.
- **Facility Standard**: All 150 seats are located in an air-conditioned, silent study hall with individual power sockets and ergonomic chairs.
- **Pricing**: Fixed fee of **₹800 for 30 calendar days** per seat.

---

## 2. Domain Models & Business Logic

### 2.1 Seat Topology & State Management
- The system manages a fixed universe of 150 seats (IDs / Numbers `1` through `150`).
- **Seat Statuses**:
  - `AVAILABLE`: Seat is unallocated and open for new bookings.
  - `OCCUPIED`: Seat is currently assigned to an active member whose 30-day period is ongoing.
  - `EXPIRING_SOON`: Active membership has 4 or fewer days remaining before expiration (renewal reminders at 4 days and 3 days before expiry).
  - `GRACE_PERIOD`: Membership has passed 30 days, granted an exact 48-hour (2-day) grace window before automated release.
  - `MAINTENANCE`: Seat or power socket is temporarily offline for repairs.

### 2.2 Member (Student) Profile & KYC
- **Primary Identifier**: Mobile Number (10-digit Indian standard).
- **Attributes**:
  - Full Name
  - Mobile Number (unique)
  - Email Address (optional)
  - Profile Photograph (optional)
  - Government ID Type & Number (Aadhaar / Voter ID / Driving License / Student ID)
  - Emergency Contact Number
  - Admission / Registration Date
  - Current Active Seat Number (if any)
  - Account Status (`ACTIVE`, `INACTIVE`, `BLOCKED`)

### 2.3 Booking & Allocation Workflow
1. **Seat Selection**: Member or Admin selects an `AVAILABLE` seat from the interactive 150-seat grid.
2. **Validity Calculation**: Start Date is chosen (default: today). End Date is automatically computed as `Start Date + 30 Days`.
3. **Payment Association**: Allocation is tied to a ₹800 payment record.
4. **Seat Switching / Transfer**:
   - Admin can transfer an active member from Seat $A$ to Seat $B$ (provided Seat $B$ is `AVAILABLE`).
   - The original expiration date is preserved.
5. **Renewal**:
   - Existing active members can renew their current seat or select an alternate available seat.
   - A new 30-day period is appended to the existing end date if renewed before expiry.

### 2.4 Payment Lifecycle & Receipt Generation
- **Standard Tariff**: ₹800 per 30-day cycle.
- **Accepted Payment Modes**:
  - UPI (Direct QR / VPA transaction)
  - Cash (Collected at the library reception desk)
  - Bank Transfer (IMPS / NEFT / RTGS)
- **Payment Verification Workflow**:
  - Offline/UPI submissions enter `PENDING_VERIFICATION` status with Transaction Reference (UTR) and optional payment screenshot.
  - Admin verifies receipt of funds in bank account or cash drawer and marks the payment `VERIFIED`.
  - Upon verification, the seat allocation is confirmed as `OCCUPIED`.
- **Payment Receipts**:
  - Sequential receipt numbering: `BLL-YYYYMM-XXXX` (e.g., `BLL-202608-0042`).
  - Standardized print-ready and PDF receipt containing:
    * Library Name, Address, and Contact Details
    * Receipt Number & Issue Date
    * Member Name & Mobile Number
    * Allocated Seat Number (#1–150)
    * Membership Validity Period (`Start Date` to `End Date` — 30 days)
    * Amount Paid (₹800.00)
    * Payment Mode & Transaction / UTR Reference
    * Authorized Signature Placeholder

### 2.5 Expiration & Automated Seat Release
- **Day T-4 (4 Days Before Expiry)**: Send 1st renewal reminder email & notification.
- **Day T-3 (3 Days Before Expiry)**: Send 2nd renewal reminder email & notification.
- **Day T (Expiry Date at 23:59:59)**: Status moves to `GRACE_PERIOD`.
- **Day T+2 (Grace Expiry after 48 Hours / 2 Days at 23:59:59)**:
  - If payment for renewal has not been verified or initiated, the system automatically revokes the allocation.
  - The seat is marked back to `AVAILABLE` for general booking.
  - An archival record of the expired booking is preserved in history.

### 2.6 Desk Complaints & Maintenance Ticketing
- Members can log issues tied directly to their assigned seat or general library amenities.
- **Categories**:
  - AC / Cooling & Temperature
  - Chair / Desk / Physical Furniture
  - Power Socket / Electrical
  - Lighting
  - WiFi / Internet Connectivity
  - Noise / Discipline
  - Cleanliness / Washroom
- **Ticket Lifecycle**: `OPEN` $\rightarrow$ `IN_PROGRESS` $\rightarrow$ `RESOLVED` $\rightarrow$ `CLOSED`.
- Admin notes and resolution timestamps are captured for auditing.

---

## 3. User Roles & Permissions

### 3.1 Super Admin (Owner)
- Full administrative rights across financial records, seat layout, member directory, settings, and staff accounts.
- Access to high-level analytics: Monthly gross revenue, occupancy trends, vacancy forecasts.

### 3.2 Library Desk Staff (Admin)
- Operational rights: Check-in new members, allocate/transfer seats, record and verify ₹800 cash/UPI payments, issue printed receipts, update ticket statuses.

### 3.3 Member (Student / Reader)
- Self-service portal: View current seat assignment (#1–150), remaining days countdown, payment history & receipts, submit renewal requests, submit seat-specific complaints.

---

## 4. Operational Dashboard & Reporting

### 4.1 Real-Time 150-Seat Interactive Grid
- Visual 150-grid layout displaying all 150 seats with instant visual color-coding:
  - 🟢 Green: `Available`
  - 🔴 Red: `Occupied`
  - 🟡 Amber: `Expiring Soon (<= 3 days)`
  - 🟣 Purple: `Grace Period`
  - ⚪ Gray: `Maintenance`
- Clicking any seat provides instant drawer/modal with seat details, occupant profile, validity dates, and quick actions (Renew, Vacate, Transfer, View Receipt).

### 4.2 Key Performance Indicators (KPI Cards)
- Total Capacity: 150 Seats
- Current Occupancy: Count & Percentage
- Vacant Seats: Count & Available Seat Numbers
- Expiring Soon (Watchlist: 4 & 3 Days Before Expiry)
- Pending Payment Verifications
- Monthly Revenue Collected (₹)

### 4.3 Exportable Reports
- Daily Collection Register (CSV / PDF)
- Monthly Revenue & Occupancy Report
- Active Members Register with ID numbers & emergency contacts
- Defaulters / Grace Period Report

---

## 5. Background Jobs & Scheduled Tasks (Celery + Redis)
1. **Midnight Expiry & Grace Checker (Daily at 00:01)**:
   - Scans all active seat bookings.
   - Flags allocations entering the $\le 4$ days window as `EXPIRING_SOON`.
   - Flags expired allocations as `GRACE_PERIOD`.
   - Releases seats whose 48-hour grace period has expired and resets status to `AVAILABLE`.
2. **Notification Dispatcher**:
   - Dispatches scheduled renewal reminder emails/notifications at 4 days and 3 days before expiry.
3. **Daily Digest Generator**:
   - Summarizes daily cash/UPI collections, renewals, and occupancy for the library owner.
