"""
Build the Stafforyx HR User Manual PDF from written content + captured
screenshots. Output: docs/manual/Stafforyx-User-Manual.pdf

    python docs/manual/_build_pdf.py

Pure local doc-generation tool. Not wired into the Django app.
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Image,
    PageBreak, Table, TableStyle, ListFlowable, ListItem, KeepTogether,
)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.pdfgen import canvas as canvas_mod
from PIL import Image as PILImage

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(HERE, 'screenshots')
LOGO_H = os.path.join(ROOT, 'static', 'images', 'logo_stafforyx_horizontal.png')
LOGO_SQ = os.path.join(ROOT, 'static', 'images', 'logo_stafforyx.png')
OUT = os.path.join(HERE, 'Stafforyx-User-Manual.pdf')

# ── Brand palette ────────────────────────────────────────────────────────────
NAVY   = colors.HexColor('#0D1B2A')
NAVY2  = colors.HexColor('#162436')
BLUE   = colors.HexColor('#1565C0')
CYAN   = colors.HexColor('#00BCD4')
GOLD   = colors.HexColor('#FFC107')
GRAY   = colors.HexColor('#64748b')
LIGHT  = colors.HexColor('#F4F6FA')
LINE   = colors.HexColor('#e2e8f0')
INK    = colors.HexColor('#1a1a2e')

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# ── Styles ───────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()
ST = {}
ST['h1'] = ParagraphStyle('h1', parent=styles['Heading1'], fontName='Helvetica-Bold',
                          fontSize=20, leading=24, textColor=NAVY, spaceBefore=6, spaceAfter=10)
ST['h2'] = ParagraphStyle('h2', parent=styles['Heading2'], fontName='Helvetica-Bold',
                          fontSize=14, leading=18, textColor=BLUE, spaceBefore=14, spaceAfter=6)
ST['h3'] = ParagraphStyle('h3', parent=styles['Heading3'], fontName='Helvetica-Bold',
                          fontSize=11.5, leading=15, textColor=NAVY, spaceBefore=10, spaceAfter=3)
ST['body'] = ParagraphStyle('body', parent=styles['BodyText'], fontName='Helvetica',
                            fontSize=10, leading=15, textColor=INK, alignment=TA_JUSTIFY,
                            spaceAfter=6)
ST['bullet'] = ParagraphStyle('bullet', parent=ST['body'], alignment=TA_LEFT, spaceAfter=3)
ST['caption'] = ParagraphStyle('caption', parent=styles['BodyText'], fontName='Helvetica-Oblique',
                               fontSize=8.5, leading=11, textColor=GRAY, alignment=TA_CENTER,
                               spaceBefore=4, spaceAfter=12)
ST['eyebrow'] = ParagraphStyle('eyebrow', parent=styles['BodyText'], fontName='Helvetica-Bold',
                               fontSize=8, leading=10, textColor=BLUE, spaceAfter=2)
ST['toc1'] = ParagraphStyle('toc1', fontName='Helvetica-Bold', fontSize=11, leading=18, textColor=NAVY)
ST['toc2'] = ParagraphStyle('toc2', fontName='Helvetica', fontSize=10, leading=15,
                            textColor=INK, leftIndent=14)
ST['note'] = ParagraphStyle('note', parent=ST['body'], fontSize=9.5, leading=14,
                            textColor=NAVY, leftIndent=8, spaceAfter=6)

# ── Flowable helpers ─────────────────────────────────────────────────────────
story = []


def H1(text, bookmark=None):
    p = Paragraph(text, ST['h1'])
    p._toc = ('1', text)
    story.append(p)


def H2(text):
    p = Paragraph(text, ST['h2'])
    p._toc = ('2', text)
    story.append(p)


def H3(text):
    story.append(Paragraph(text, ST['h3']))


def P(text):
    story.append(Paragraph(text, ST['body']))


def BULLETS(items):
    flow = [ListItem(Paragraph(t, ST['bullet']), value='•') for t in items]
    story.append(ListFlowable(flow, bulletType='bullet', start='•',
                              leftIndent=14, bulletColor=BLUE, spaceAfter=8))


def NUMBERS(items):
    flow = [ListItem(Paragraph(t, ST['bullet'])) for t in items]
    story.append(ListFlowable(flow, bulletType='1', leftIndent=16,
                              bulletColor=BLUE, spaceAfter=8))


def NOTE(text, label='Tip', color=BLUE):
    inner = Paragraph(f'<b>{label}:</b> {text}', ST['note'])
    t = Table([[inner]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT),
        ('LINEBEFORE', (0, 0), (0, -1), 3, color),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.append(Spacer(1, 2))
    story.append(t)
    story.append(Spacer(1, 8))


def SHOT(name, caption, max_h=205 * mm):
    path = os.path.join(SHOTS, name)
    if not os.path.exists(path):
        return
    iw, ih = PILImage.open(path).size
    max_w = CONTENT_W
    scale = min(max_w / iw, max_h / ih)
    w, h = iw * scale, ih * scale
    img = Image(path, width=w, height=h)
    img.hAlign = 'CENTER'
    # framed
    frame = Table([[img]], colWidths=[w])
    frame.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, LINE),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    frame.hAlign = 'CENTER'
    story.append(Spacer(1, 4))
    story.append(frame)
    story.append(Paragraph(caption, ST['caption']))


def SPACE(h=6):
    story.append(Spacer(1, h))


def table_rows(rows, col_widths, header=True):
    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    cmds = [
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), INK),
        ('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]
    if header:
        cmds += [
            ('BACKGROUND', (0, 0), (-1, 0), NAVY),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 9),
        ]
    t.setStyle(TableStyle(cmds))
    story.append(t)
    story.append(Spacer(1, 8))


# ── Page furniture (cover, header, footer) ───────────────────────────────────
def draw_cover(c, doc):
    c.saveState()
    c.setFillColor(NAVY)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # accent bars
    c.setFillColor(BLUE)
    c.rect(0, PAGE_H - 8 * mm, PAGE_W, 8 * mm, fill=1, stroke=0)
    c.setFillColor(CYAN)
    c.rect(0, PAGE_H - 10 * mm, PAGE_W, 2 * mm, fill=1, stroke=0)
    # logo
    try:
        iw, ih = PILImage.open(LOGO_H).size
        lw = 78 * mm
        lh = lw * ih / iw
        c.drawImage(LOGO_H, (PAGE_W - lw) / 2, PAGE_H * 0.62,
                    width=lw, height=lh, mask='auto', preserveAspectRatio=True)
    except Exception:
        pass
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 30)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.50, 'User Manual')
    c.setFillColor(CYAN)
    c.setFont('Helvetica-Bold', 12)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.455, 'HR  &  PAYROLL  MANAGEMENT  SYSTEM')
    c.setFillColor(colors.HexColor('#8aa0b8'))
    c.setFont('Helvetica', 11)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.40,
                        'Complete guide & reference for administrators and employees')
    # footer block
    c.setFillColor(BLUE)
    c.rect(0, 0, PAGE_W, 22 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 11)
    c.drawCentredString(PAGE_W / 2, 13 * mm, 'Stafforyx HR')
    c.setFillColor(colors.HexColor('#cfe3ff'))
    c.setFont('Helvetica', 9)
    c.drawCentredString(PAGE_W / 2, 7.5 * mm, 'by SYNTRIX PH')
    c.restoreState()


def header_footer(c, doc):
    c.saveState()
    # header rule
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(MARGIN, PAGE_H - 12 * mm, PAGE_W - MARGIN, PAGE_H - 12 * mm)
    c.setFillColor(GRAY)
    c.setFont('Helvetica', 8)
    c.drawString(MARGIN, PAGE_H - 10.5 * mm, 'Stafforyx HR — User Manual')
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 10.5 * mm, 'by SYNTRIX PH')
    # footer
    c.setStrokeColor(LINE)
    c.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
    c.setFillColor(GRAY)
    c.drawString(MARGIN, 9 * mm, 'Confidential — for internal use')
    c.setFillColor(NAVY)
    c.setFont('Helvetica-Bold', 9)
    c.drawRightString(PAGE_W - MARGIN, 9 * mm, f'{doc.page}')
    c.restoreState()


class ManualDoc(BaseDocTemplate):
    def __init__(self, filename, **kw):
        super().__init__(filename, pagesize=A4,
                         leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=20 * mm, bottomMargin=18 * mm, **kw)
        frame = Frame(MARGIN, 16 * mm, CONTENT_W, PAGE_H - 36 * mm, id='body')
        self.addPageTemplates([
            PageTemplate(id='cover', frames=[frame], onPage=draw_cover),
            PageTemplate(id='content', frames=[frame], onPage=header_footer),
        ])

    def afterFlowable(self, flowable):
        toc = getattr(flowable, '_toc', None)
        if toc:
            level, text = toc
            key = f'toc-{id(flowable)}'
            self.canv.bookmarkPage(key)
            self.notify('TOCEntry', (0 if level == '1' else 1, text, self.page, key))


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CONTENT                                                                   ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# Cover page is page 1 (cover template). Force a page break to start content.
story.append(PageBreak())

# ── Table of contents ────────────────────────────────────────────────────────
toc = TableOfContents()
toc.levelStyles = [ST['toc1'], ST['toc2']]
story.append(Paragraph('Contents', ST['h1']))
story.append(Spacer(1, 6))
story.append(toc)
story.append(PageBreak())

# ── 1. Overview ──────────────────────────────────────────────────────────────
H1('1.  Overview')
P('<b>Stafforyx HR</b> is a complete human-resources and payroll management system built by '
  'SYNTRIX PH. It centralises everything an organisation needs to manage its workforce — '
  'employee records, attendance, leaves, holidays, overtime, payroll, payslips, documents, '
  'announcements and reporting — inside one secure, easy-to-use application.')
P('The system is designed for the Philippine setting: payroll follows local pay practices '
  '(daily and monthly pay bases, regular and special holidays, night/rest-day handling, and the '
  'standard SSS, PhilHealth, Pag-IBIG and withholding-tax deductions), while the interface stays '
  'simple enough for any HR officer to use without training.')

H2('Who uses Stafforyx')
BULLETS([
    '<b>Administrators / HR officers</b> — manage employees, attendance, payroll, and company settings.',
    '<b>Managers</b> — review and approve leaves and overtime for their people.',
    '<b>Payroll officers</b> — generate payroll, produce and send payslips.',
    '<b>Employees</b> — use the self-service <b>Employee Portal</b> to clock in/out, file leaves and overtime, and view their payslips.',
])

H2('Key capabilities at a glance')
BULLETS([
    '<b>Multi-company</b> — one installation can manage several companies, each with its own employees, settings and payslip branding.',
    '<b>Role-based access</b> — every user only sees the modules and companies they are permitted to.',
    '<b>Attendance</b> — manual entry, WiFi/IP self-service portal, and biometric-device ready.',
    '<b>Flexible scheduling</b> — fixed work schedules or per-day shift assignments, plus flexible-hours employees.',
    '<b>Smart payroll</b> — computes pay from real attendance, leaves and holidays; supports daily and monthly pay bases.',
    '<b>Branded payslips</b> — per-company accent colour, logo, footer note and an auto-filled "Prepared By" signature.',
    '<b>Reports & exports</b> — employee, attendance and payroll reports with data export.',
    '<b>Installable app (PWA)</b> — can be installed on desktop and mobile for quick access.',
])

H2('How the system is organised')
P('Stafforyx is divided into modules, reached from the left-hand sidebar. The table below maps '
  'each sidebar item to what it does — the rest of this manual walks through each one in detail.')
table_rows(
    [['Sidebar', 'Module', 'What it is for'],
     ['Dashboard', 'Dashboard', 'At-a-glance summary of the organisation today.'],
     ['Employees', 'Employees', 'The master list of staff and their records.'],
     ['Companies', 'Companies', 'Company records and payslip configuration.'],
     ['Attendance', 'Attendance & Schedules', 'Daily attendance and work-schedule setup.'],
     ['Leave Management', 'Leaves', 'Leave requests, approvals and balances.'],
     ['Payroll', 'Payroll', 'Periods, payroll generation and payslips.'],
     ['Holidays', 'Holidays', 'Holiday calendar and pay rules.'],
     ['Documents', 'Documents', 'Employee document storage.'],
     ['Announcements', 'Announcements', 'Company-wide and targeted notices.'],
     ['Reports', 'Reports', 'Reports and data exports.'],
     ['(Profile menu)', 'Users / Theme / License', 'Access control, appearance and licensing.'],
     ['Employee Portal', 'Portal', 'Employee self-service area.']],
    [28 * mm, 42 * mm, CONTENT_W - 70 * mm])

# ── 2. Core concepts ─────────────────────────────────────────────────────────
H1('2.  Core concepts')

H2('Companies (multi-company)')
P('Everything in Stafforyx belongs to a <b>company</b>. Employees, attendance, payroll and '
  'settings are all company-scoped, so data from one company never mixes with another. '
  'Administrators with access to more than one company can switch between them where relevant '
  '(for example, the Payslip Settings page has a company picker in the top-right).')

H2('Roles & permissions')
P('Access is controlled by each user’s <b>role</b> and the individual <b>module permissions</b> '
  'on their profile. A user only ever sees what they are allowed to:')
table_rows(
    [['Role', 'Typical use', 'Sees'],
     ['Super Admin', 'System owner / SYNTRIX PH', 'Everything, all companies.'],
     ['HR Admin', 'HR officer', 'The modules enabled on their profile, for their companies.'],
     ['Manager', 'Team lead', 'Approvals and the modules they are granted.'],
     ['Employee', 'Staff member', 'Only the Employee Portal (self-service).']],
    [32 * mm, 42 * mm, CONTENT_W - 74 * mm])
NOTE('A user must have a <b>role other than Employee</b>, be <b>Active in Stafforyx</b>, have the '
     'specific module permission switched on (e.g. <i>Can manage payroll</i>), and be <b>assigned '
     'to at least one company</b> before they can open and use a management module.', label='Important', color=GOLD)

H2('Licensing')
P('Stafforyx runs against a license. When a license is active the app is fully editable. If a '
  'license is expired/inactive — or the computer clock is rolled back — the app switches to a '
  'read-only state and shows a banner; you can still view data, but saving changes is blocked '
  'until the license is restored from the <b>License Status</b> page.')

# ── 3. Getting started ───────────────────────────────────────────────────────
H1('3.  Getting started')

H2('Signing in')
P('Open the application URL in your browser and sign in with the username and password provided '
  'by your administrator.')
SHOT('01_login.png', 'Figure 3.1 — The Stafforyx sign-in screen.', max_h=150 * mm)
NOTE('Stafforyx is a Progressive Web App. In Chrome/Edge you can install it (the install icon in '
     'the address bar) to launch it like a desktop or mobile app.')

H2('Finding your way around')
P('After signing in you land on the <b>Dashboard</b>. The fixed <b>sidebar</b> on the left groups '
  'the modules (Main, People, Workforce, Finance, Admin/Management). The <b>top bar</b> shows the '
  'current page and your profile menu. Your profile menu (top-right) is where you reach the '
  'Employee Portal, Users, Theme, License Status and Payslip Settings, and where you log out.')

H2('Personalising the sidebar (Theme)')
P('From your profile menu choose <b>Theme</b> to recolour the sidebar to your liking — pick a '
  'preset or any custom colour, with a live preview. The choice is saved to your account, so it '
  'follows you on every device and does not affect other users.')
SHOT('17_theme.png', 'Figure 3.2 — Theme: personalise your sidebar colour.')

# ── 4. Modules ───────────────────────────────────────────────────────────────
H1('4.  Modules')

H2('4.1  Dashboard')
P('The Dashboard gives an at-a-glance picture of your organisation today: active employees, who '
  'is present, pending leaves, and current-period payroll, plus quick-action shortcuts and recent '
  'activity (employees, attendance, leave requests and announcements).')
SHOT('02_dashboard.png', 'Figure 4.1 — The main Dashboard.')

H2('4.2  Employees')
P('The Employees module is the master list of your staff. From here you can search, filter by '
  'status or department, and open any employee to view or edit their full record.')
H3('Adding or editing an employee')
NUMBERS([
    'Click <b>Add New Employee</b> (or the edit icon on an existing row).',
    'Fill in personal details, company, employee ID, department and position.',
    'Set <b>Pay Basis</b> (Daily or Monthly), the <b>Basic Salary</b>, and — for daily-paid staff — the <b>Daily Rate</b>.',
    'Optionally assign a <b>Work Schedule</b>, biometric ID, government numbers and fixed contribution amounts.',
    'Save. The employee now appears in the list and is available to attendance and payroll.',
])
NOTE('Monthly employees are paid from <b>Basic Salary</b>; daily employees are paid from <b>Daily '
     'Rate</b>. If a daily employee’s rate is left blank, the system computes it from Basic Salary ÷ 26.')
SHOT('03_employees.png', 'Figure 4.2 — Employees list with Pay Basis, Basic Salary and Daily Rate columns.')
SHOT('04_employee_detail.png', 'Figure 4.3 — An employee’s detail record.')

H2('4.3  Attendance & Schedules')
P('Attendance records the days your employees work. Records can be entered manually, captured '
  'through the WiFi/IP <b>Employee Portal</b> time clock, or imported from biometric devices. Each '
  'record carries a date, time-in/out, computed late/undertime/overtime minutes and a status '
  '(Present, Late, Half Day, On Leave or Absent).')
SHOT('05_attendance.png', 'Figure 4.4 — Attendance list.')
H3('Work schedules')
P('A <b>Work Schedule</b> defines an employee’s normal working days and hours (start/end time, '
  'grace period, required hours and which weekdays are working days). For day-to-day changes you '
  'can also assign per-date <b>shift templates</b> or rest days. Schedules drive how attendance is '
  'classified and how payroll counts scheduled vs. absent days.')
SHOT('06_schedules.png', 'Figure 4.5 — Work schedules.')
NOTE('Payroll honours the attendance <b>status</b>, not just clock-in time. A day marked '
     '<b>Present</b> counts even without a recorded time-in; <b>Half Day</b> pays 0.5; <b>On Leave</b> '
     'is handled by the leave module; and explicit <b>Absent</b> is not paid. Employees without a '
     'work schedule are still paid from their actual attendance.')

H2('4.4  Leave Management')
P('The Leaves module handles the full leave workflow: employees (or HR) file a request, a manager '
  'or HR reviews it, and approved leaves automatically flow into payroll. Paid leave is counted as '
  'payable days; unpaid leave is excluded but does not count as an absence.')
SHOT('07_leaves.png', 'Figure 4.6 — Leave requests list.')
H3('Approving or rejecting')
NUMBERS([
    'Open <b>Leave Management</b> and review the pending requests.',
    'Open a request to see the dates, type (paid/unpaid) and reason.',
    'Click <b>Approve</b> or <b>Reject</b>. Approved leaves are picked up the next time payroll is generated.',
])

H2('4.5  Holidays')
P('The Holidays module is the company holiday calendar. Each holiday has a type (regular or '
  'special), a paid/unpaid flag, a no-work pay percentage and a worked-day multiplier. Payroll '
  'uses these rules automatically — for example, an employee who works a regular holiday is paid '
  'the holiday multiplier, while a no-work paid holiday still pays the configured percentage.')
SHOT('11_holidays.png', 'Figure 4.7 — Holiday calendar and pay rules.')

H2('4.6  Overtime')
P('Overtime is governed per employee by an <b>overtime policy</b> (not allowed, automatic, request '
  'required, or management review). Where requests are required, employees file overtime from the '
  'portal and HR/managers approve it here. Only <b>approved/payable</b> overtime is paid by payroll.')
SHOT('15_overtime.png', 'Figure 4.8 — Overtime management.')

H2('4.7  Payroll')
P('Payroll is where pay is calculated and payslips are produced. The workflow has three parts: '
  'define a <b>payroll period</b>, <b>generate</b> the payroll for that period, then review and '
  'issue <b>payslips</b>.')
H3('Generating payroll')
NUMBERS([
    'Create a <b>Payroll Period</b> (name, start and end dates, optional pay date).',
    'Open <b>Generate Payroll</b>, choose the period (and optionally a department).',
    'Leave <b>Recalculate existing Draft records</b> ticked to refresh drafts with the latest attendance.',
    'Generate. Stafforyx computes each employee’s pay from attendance, leaves and holidays.',
    'Review the resulting records; approved/paid records are never overwritten.',
])
SHOT('09_payroll_generate.png', 'Figure 4.9 — Generate Payroll.')
SHOT('08_payroll.png', 'Figure 4.10 — Payroll records list.')
H3('Payslips')
P('Open any record to see its payslip — a clean, branded document with the rate information, '
  'attendance summary, full earnings/deductions breakdown and net pay. You can <b>Print / Save as '
  'PDF</b> or <b>Send to Employee</b> by email. Employees can also view their own payslips in the '
  'portal.')
SHOT('10_payslip.png', 'Figure 4.11 — A generated payslip.')

H2('4.8  Payslip Settings (per company)')
P('Each company controls how its payslips look and read. Reach this from the profile menu '
  '(<b>Payslip Settings</b>) or via Payroll. Here you set the display name and address, accent '
  'colour, which sections appear, a footer note, and the <b>Prepared By</b> block — a preparer '
  'name, title and a signature you can either <b>upload</b> or <b>draw</b> on screen. The signature '
  'and name then appear automatically on every payslip for that company. Use the company picker '
  '(top-right) to configure a different company.')
SHOT('18_payslip_settings.png', 'Figure 4.12 — Payslip Settings, including Prepared By & signature.')

H2('4.9  Documents')
P('Store employee documents (contracts, IDs, certificates and similar) against each employee. '
  'Files can be uploaded, listed, downloaded and removed, keeping HR paperwork in one place.')
SHOT('12_documents.png', 'Figure 4.13 — Employee documents.')

H2('4.10  Announcements')
P('Post company-wide or targeted announcements (for example, to a specific department). '
  'Announcements appear on the management dashboard and in the Employee Portal so staff stay '
  'informed.')
SHOT('13_announcements.png', 'Figure 4.14 — Announcements.')

H2('4.11  Reports')
P('The Reports module provides employee, attendance and payroll reporting, with data export so '
  'you can take figures into spreadsheets or share them with management.')
SHOT('14_reports.png', 'Figure 4.15 — Reports dashboard.')

H2('4.12  Users & Access')
P('Super Admins manage application users from <b>Users</b> (profile menu). Here you create a user, '
  'set their role, switch on the exact module permissions they need, mark them active, and assign '
  'the companies they may access. This is how you safely add another administrator without giving '
  'them full super-admin powers.')
SHOT('16_users.png', 'Figure 4.16 — Users & access management.')

H2('4.13  License Status')
P('The License Status page shows the current licensing state and lets an authorised user activate '
  'or renew the license. If the app ever becomes read-only, this is where you restore full access.')
SHOT('19_license.png', 'Figure 4.17 — License status.')

H2('4.14  Employee Portal')
P('The Employee Portal is the self-service area for staff. After signing in, an employee can clock '
  'in/out (where the WiFi/IP time clock is enabled), file leaves and overtime, read announcements, '
  'access their documents and view or download their payslips — without seeing any management data.')
SHOT('20_portal.png', 'Figure 4.18 — Employee Portal dashboard.')
SHOT('21_portal_payslips.png', 'Figure 4.19 — Employee Portal: my payslips.')

# ── 5. Payroll computation reference ─────────────────────────────────────────
H1('5.  Payroll computation reference')
P('This section explains, in plain terms, how Stafforyx turns attendance into pay. You do not '
  'need to memorise it — the system does the maths — but it helps when reviewing figures.')
H2('Rates')
BULLETS([
    '<b>Daily rate</b> — a daily-paid employee uses their <b>Daily Rate</b>; otherwise it is Basic Salary ÷ 26.',
    '<b>Hourly rate</b> — daily rate ÷ 8.',
])
H2('Days and pay')
BULLETS([
    '<b>Scheduled days</b> — the days an employee is expected to work in the period.',
    '<b>Present days</b> — days the employee actually worked (by attendance status); Half Day counts as 0.5.',
    '<b>Paid leave</b> — approved paid-leave days on scheduled working days; counted as payable.',
    '<b>Absent days</b> — scheduled days with no presence and no leave (informational; already excluded from basic pay).',
    '<b>Payable days</b> — present days + paid-leave days. <b>Basic pay</b> = daily rate × payable days.',
])
H2('Additions and deductions')
BULLETS([
    '<b>Overtime pay</b> — approved overtime minutes ÷ 60 × hourly rate × 1.25.',
    '<b>Holiday pay</b> — worked holidays pay the holiday multiplier; no-work paid holidays pay the configured percentage.',
    '<b>Late / undertime</b> — deducted as (minutes ÷ 60) × hourly rate.',
    '<b>Statutory</b> — fixed SSS, PhilHealth, Pag-IBIG and withholding tax from the employee record.',
    '<b>Adjustments</b> — one-off earnings (e.g. bonus, allowance) or deductions (e.g. cash advance) added per record.',
])
NOTE('<b>Net pay = Gross pay − Total deductions.</b> Absent days are already removed from basic pay, '
     'so they are shown for information only and are never deducted a second time.')

# ── 6. Tips & troubleshooting ────────────────────────────────────────────────
H1('6.  Tips & troubleshooting')
H3('Payroll shows zero or looks wrong')
BULLETS([
    'Make sure the employee has <b>attendance</b> in the period and a <b>Basic Salary</b>/<b>Daily Rate</b>.',
    'Regenerate the period with <b>Recalculate existing Draft records</b> ticked, or delete the draft and regenerate.',
    'Check the <b>payroll period dates</b> actually cover the attendance dates.',
])
H3('A new administrator cannot open a module')
BULLETS([
    'Confirm their <b>role is not Employee</b> and they are <b>Active in Stafforyx</b>.',
    'Switch on the specific permission (e.g. <i>Can manage payroll</i>).',
    'Assign them to <b>at least one company</b> — without a company they will see no data.',
])
H3('The app is read-only / shows a license banner')
BULLETS([
    'Check the computer date/time is correct (a rolled-back clock triggers read-only).',
    'Open <b>License Status</b> and renew/activate the license.',
])
H3('A payslip looks off')
BULLETS([
    'Set the <b>Prepared By</b> name, title and signature in <b>Payslip Settings</b> for that company.',
    'For a clean signature, upload a <b>transparent PNG</b> or use the on-screen <b>Draw</b> option.',
    'Adjust the accent colour and visible sections in Payslip Settings.',
])

# ── 7. Appendix: permission reference ────────────────────────────────────────
H1('Appendix A.  Permission reference')
P('Each user profile exposes the following module permissions. Grant only what the person needs.')
table_rows(
    [['Permission', 'Grants access to'],
     ['Can access dashboard', 'The main Dashboard.'],
     ['Can manage employees', 'Employee records.'],
     ['Can manage attendance', 'Attendance & schedules.'],
     ['Can manage leaves', 'Leave requests and approvals.'],
     ['Can manage payroll', 'Payroll periods, generation and payslips.'],
     ['Can manage documents', 'Employee documents.'],
     ['Can manage announcements', 'Posting announcements.'],
     ['Can view reports', 'Reports and exports.'],
     ['Can manage users', 'User & access management.'],
     ['Can manage settings', 'Company / payslip settings.'],
     ['Can manage license', 'License activation.']],
    [62 * mm, CONTENT_W - 62 * mm])
SPACE(6)
P('<i>This manual was generated for Stafforyx HR by SYNTRIX PH. Screens shown use sample data; your '
  'figures and branding will differ.</i>')


# ── Build ────────────────────────────────────────────────────────────────────
def build():
    doc = ManualDoc(OUT)
    # first template is cover, then switch to content after the first PageBreak
    story.insert(0, _SetTemplate('content'))
    doc.multiBuild(story)
    print('PDF written:', OUT)


from reportlab.platypus.doctemplate import NextPageTemplate as _SetTemplate

if __name__ == '__main__':
    build()
