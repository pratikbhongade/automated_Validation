import os
import pythoncom
import win32com.client as win32
from datetime import datetime

def send_email(subject, validation_results, success, log_file_path):
    """Send a beautifully formatted email with validation results"""
    # Email header with logo and title
    email_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
            .header {{ text-align: center; padding-bottom: 20px; border-bottom: 1px solid #eaeaea; }}
            .logo {{ max-height: 60px; }}
            .result-container {{ background: #f9f9f9; border-radius: 5px; padding: 15px; margin: 20px 0; }}
            .result-item {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
            .success {{ color: #28a745; font-weight: bold; }}
            .failed {{ color: #dc3545; font-weight: bold; }}
            .skipped {{ color: #ffc107; font-weight: bold; }}
            .status-banner {{ 
                padding: 15px; 
                text-align: center; 
                font-size: 18px; 
                font-weight: bold; 
                border-radius: 5px;
                margin: 20px 0;
            }}
            .success-banner {{ background-color: #d4edda; color: #155724; }}
            .failed-banner {{ background-color: #f8d7da; color: #721c24; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eaeaea; }}
            .timestamp {{ color: #6c757d; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <!-- Replace with your actual logo URL or attachment -->
                <h2>FPA IT Application Validation Report</h2>
            </div>
            
            <p>Dear Team,</p>
            
            <p>Please find below the validation results for <strong>FPA IT Application</strong>:</p>
            
            <div class="result-container">
                <h3>Validation Details:</h3>
    """

    # Add validation results with proper styling
    for result, status in validation_results:
        status_class = "success" if status == "Success" else "failed" if status == "Failed" else "skipped"
        email_body += f"""
        <div class="result-item">
            <span class="{status_class}">[{status}]</span> {result}
        </div>
        """

    # Add status banner
    if success:
        email_body += """
            </div>
            <div class="status-banner success-banner">
                ✅ Validation Completed Successfully
            </div>
        """
    else:
        email_body += """
            </div>
            <div class="status-banner failed-banner">
                ❌ Validation Completed With Failures
            </div>
        """

    # Email footer
    email_body += f"""
            <div class="footer">
                <p>Best regards,</p>
                <p><strong>Your Name</strong><br>
                Your Position<br>
                Your Contact Information</p>
                
                <p class="timestamp">Report generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        </div>
    </body>
    </html>
    """

    pythoncom.CoInitialize()
    try:
        outlook = win32.Dispatch('outlook.application')
        mail = outlook.CreateItem(0)
        mail.To = 'Pratik_Bhongade@keybank.com'  # Replace with actual recipient(s)
        mail.CC = 'team@example.com'  # Add CC recipients if needed
        mail.Subject = subject
        mail.HTMLBody = email_body

        # Add multiple attachments if needed
        attachments = [log_file_path]
        for attachment in attachments:
            if os.path.exists(attachment):
                mail.Attachments.Add(attachment)
            else:
                print(f"Attachment not found: {attachment}")

        # Uncomment to display email before sending (for testing)
        # mail.Display(True)  
        mail.Send()
        
        print("Email sent successfully!")
        
    except Exception as e:
        print(f"Failed to send email: {str(e)}")
        # Consider adding retry logic here for transient failures
        raise
    finally:
        pythoncom.CoUninitialize()
