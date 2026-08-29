from io import BytesIO

from django.conf import settings
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib import colors


def generate_receipt_pdf(receipt) -> bytes:
    """
    Generate an official payment receipt PDF entirely in memory.

    No PDF file is written to disk or stored in MEDIA_ROOT.
    The returned bytes can be downloaded directly or attached to email.
    """

    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Receipt {receipt.receipt_number}",
        author="Bhagya Laxmi Library",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReceiptTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=20,
        leading=24,
        spaceAfter=6,
    )

    subtitle_style = ParagraphStyle(
        "ReceiptSubtitle",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=18,
    )

    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=12,
        leading=16,
        spaceBefore=12,
        spaceAfter=8,
        textColor=colors.HexColor("#0f172a"),
    )

    normal_style = ParagraphStyle(
        "ReceiptNormal",
        parent=styles["Normal"],
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#334155"),
    )

    small_style = ParagraphStyle(
        "ReceiptSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#64748b"),
    )

    story = []

    story.append(
        Paragraph(
            "BHAGYA LAXMI LIBRARY",
            title_style,
        )
    )

    story.append(
        Paragraph(
            "Official Payment Receipt",
            subtitle_style,
        )
    )

    receipt_summary = [
        [
            Paragraph("<b>Receipt Number</b>", normal_style),
            Paragraph(
                str(receipt.receipt_number),
                normal_style,
            ),
        ],
        [
            Paragraph("<b>Issued On</b>", normal_style),
            Paragraph(
                receipt.issued_at.strftime("%d %b %Y, %I:%M %p"),
                normal_style,
            ),
        ],
    ]

    summary_table = Table(
        receipt_summary,
        colWidths=[55 * mm, 105 * mm],
        hAlign="CENTER",
    )

    summary_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#f1f5f9"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.7,
                    colors.HexColor("#cbd5e1"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#e2e8f0"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
            ]
        )
    )

    story.append(summary_table)

    story.append(
        Paragraph(
            "Student Information",
            section_style,
        )
    )

    student_data = [
        [
            Paragraph("<b>Name</b>", normal_style),
            Paragraph(
                str(receipt.student_name),
                normal_style,
            ),
        ],
        [
            Paragraph("<b>Phone</b>", normal_style),
            Paragraph(
                str(receipt.student_phone),
                normal_style,
            ),
        ],
        [
            Paragraph("<b>Seat Number</b>", normal_style),
            Paragraph(
                f"#{receipt.seat_number}",
                normal_style,
            ),
        ],
    ]

    student_table = Table(
        student_data,
        colWidths=[55 * mm, 105 * mm],
        hAlign="CENTER",
    )

    student_table.setStyle(
        TableStyle(
            [
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.7,
                    colors.HexColor("#cbd5e1"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#e2e8f0"),
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#f8fafc"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
            ]
        )
    )

    story.append(student_table)

    story.append(
        Paragraph(
            "Membership Details",
            section_style,
        )
    )

    membership_data = [
        [
            Paragraph("<b>Membership Start</b>", normal_style),
            Paragraph(
                receipt.membership_start.strftime(
                    "%d %b %Y, %I:%M %p"
                ),
                normal_style,
            ),
        ],
        [
            Paragraph("<b>Membership Expires</b>", normal_style),
            Paragraph(
                receipt.membership_expires_at.strftime(
                    "%d %b %Y, %I:%M %p"
                ),
                normal_style,
            ),
        ],
    ]

    membership_table = Table(
        membership_data,
        colWidths=[55 * mm, 105 * mm],
        hAlign="CENTER",
    )

    membership_table.setStyle(
        TableStyle(
            [
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.7,
                    colors.HexColor("#cbd5e1"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#e2e8f0"),
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#f8fafc"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
            ]
        )
    )

    story.append(membership_table)

    story.append(
        Paragraph(
            "Payment Details",
            section_style,
        )
    )

    payment_data = [
        [
            Paragraph("<b>Amount Paid</b>", normal_style),
            Paragraph(
                f"₹{receipt.amount_paid:.2f}",
                normal_style,
            ),
        ],
        [
            Paragraph("<b>Payment Mode</b>", normal_style),
            Paragraph(
                str(receipt.payment.get_payment_mode_display()),
                normal_style,
            ),
        ],
        [
            Paragraph("<b>UTR Reference</b>", normal_style),
            Paragraph(
                receipt.utr_reference or "—",
                normal_style,
            ),
        ],
    ]

    payment_table = Table(
        payment_data,
        colWidths=[55 * mm, 105 * mm],
        hAlign="CENTER",
    )

    payment_table.setStyle(
        TableStyle(
            [
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.7,
                    colors.HexColor("#cbd5e1"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#e2e8f0"),
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#f8fafc"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
            ]
        )
    )

    story.append(payment_table)

    story.append(Spacer(1, 18))

    story.append(
        Paragraph(
            "This is an electronically generated official payment receipt "
            "for Bhagya Laxmi Library. Please retain it for your records.",
            small_style,
        )
    )

    story.append(Spacer(1, 6))

    story.append(
        Paragraph(
            "Payment verified by library administration.",
            small_style,
        )
    )

    document.build(story)

    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes
