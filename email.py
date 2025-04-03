def send_email(subject, validation_results, success, log_file_path):
    """Send a beautifully formatted email with validation results"""
    # Calculate summary statistics
    total_checks = len(validation_results)
    success_count = sum(1 for _, status in validation_results if status == "Success")
    failed_count = sum(1 for _, status in validation_results if status == "Failed")
    skipped_count = sum(1 for _, status in validation_results if status == "Skipped")
    success_rate = (success_count / total_checks * 100) if total_checks > 0 else 0

    # Email template with enhanced styling
    email_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
            .header {{ 
                text-align: center; 
                padding-bottom: 20px; 
                border-bottom: 1px solid #eaeaea;
                background-color: #f8f9fa;
                padding: 20px;
                border-radius: 5px;
            }}
            .logo {{ max-height: 60px; }}
            
            /* Summary Section Styling */
            .summary-container {{
                background: #e9ecef;
                border-radius: 5px;
                padding: 20px;
                margin: 25px 0;
                border-left: 5px solid {'#28a745' if success else '#dc3545'};
            }}
            .summary-title {{
                font-size: 18px;
                font-weight: bold;
                margin-bottom: 15px;
                color: {'#28a745' if success else '#dc3545'};
            }}
            .summary-stats {{
                display: flex;
                justify-content: space-between;
                flex-wrap: wrap;
            }}
            .stat-box {{
                background: white;
                border-radius: 5px;
                padding: 10px 15px;
                margin: 5px;
                flex: 1;
                min-width: 120px;
                text-align: center;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .stat-value {{
                font-size: 24px;
                font-weight: bold;
            }}
            .stat-label {{
                font-size: 12px;
                color: #6c757d;
            }}
            .success-stat {{ color: #28a745; }}
            .failed-stat {{ color: #dc3545; }}
            .skipped-stat {{ color: #ffc107; }}
            
            /* Results Section Styling */
            .result-container {{ 
                background: #f9f9f9; 
                border-radius: 5px; 
                padding: 15px; 
                margin: 20px 0;
                border: 1px solid #eaeaea;
            }}
            .result-item {{ 
                padding: 8px 0; 
                border-bottom: 1px solid #eee; 
                display: flex;
            }}
            .result-index {{
                font-weight: bold;
                margin-right: 10px;
                color: #6c757d;
                min-width: 30px;
            }}
            .success {{ color: #28a745; font-weight: bold; }}
            .failed {{ color: #dc3545; font-weight: bold; }}
            .skipped {{ color: #ffc107; font-weight: bold; }}
            
            /* Status Banner */
            .status-banner {{ 
                padding: 15px; 
                text-align: center; 
                font-size: 18px; 
                font-weight: bold; 
                border-radius: 5px;
                margin: 20px 0;
            }}
            .success-banner {{ 
                background-color: #d4edda; 
                color: #155724;
                border-left: 5px solid #28a745;
            }}
            .failed-banner {{ 
                background-color: #f8d7da; 
                color: #721c24;
                border-left: 5px solid #dc3545;
            }}
            
            /* Footer */
            .footer {{ 
                margin-top: 30px; 
                padding-top: 20px; 
                border-top: 1px solid #eaeaea;
                font-size: 14px;
            }}
            .timestamp {{ 
                color: #6c757d; 
                font-size: 12px;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>FPA IT Application Validation Report</h2>
            </div>
            
            <p>Dear Team,</p>
            
            <p>Please find below the validation results for <strong>FPA IT Application</strong>:</p>
            
            <!-- Enhanced Summary Section -->
            <div class="summary-container">
                <div class="summary-title">Validation Summary</div>
                <div class="summary-stats">
                    <div class="stat-box">
                        <div class="stat-value">{total_checks}</div>
                        <div class="stat-label">Total Checks</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value success-stat">{success_count}</div>
                        <div class="stat-label">Successful</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value failed-stat">{failed_count}</div>
                        <div class="stat-label">Failed</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value skipped-stat">{skipped_count}</div>
                        <div class="stat-label">Skipped</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value">{success_rate:.1f}%</div>
                        <div class="stat-label">Success Rate</div>
                    </div>
                </div>
            </div>
            
            <!-- Detailed Results -->
            <div class="result-container">
                <h3>Detailed Validation Results:</h3>
    """

    # Add validation results with numbering and improved formatting
    for i, (result, status) in enumerate(validation_results, 1):
        status_class = "success" if status == "Success" else "failed" if status == "Failed" else "skipped"
        email_body += f"""
        <div class="result-item">
            <div class="result-index">{i}.</div>
            <div><span class="{status_class}">[{status}]</span> {result}</div>
        </div>
        """

    # Add status banner
    if success:
        email_body += """
            </div>
            <div class="status-banner success-banner">
                ✅ Validation Completed Successfully - All checks passed
            </div>
        """
    else:
        email_body += """
            </div>
            <div class="status-banner failed-banner">
                ❌ Validation Completed With Failures - Please review the failed checks
            </div>
        """

    # Email footer
    email_body += f"""
            <div class="footer">
                <p><strong>Next Steps:</strong></p>
                <ul>
                    <li>Review the detailed results above</li>
                    <li>Check attached log file for complete details</li>
                    <li>Contact the development team for any critical failures</li>
                </ul>
                
                <p class="timestamp">
                    Report generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
                    This is an automated message - please do not reply directly
                </p>
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

        # Add attachments
        if os.path.exists(log_file_path):
            mail.Attachments.Add(log_file_path)
        else:
            print(f"Log file not found: {log_file_path}")

        mail.Send()
        print("Email sent successfully with enhanced summary section!")
        
    except Exception as e:
        print(f"Failed to send email: {str(e)}")
        raise
    finally:
        pythoncom.CoUninitialize()
