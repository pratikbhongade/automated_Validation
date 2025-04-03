def send_email(subject, validation_results, success, log_file_path):
    """Send a beautifully formatted email with validation results"""
    # Calculate summary statistics
    total_checks = len(validation_results)
    success_count = sum(1 for _, status in validation_results if status == "Success")
    failed_count = sum(1 for _, status in validation_results if status == "Failed")
    skipped_count = sum(1 for _, status in validation_results if status == "Skipped")
    success_rate = (success_count / total_checks * 100) if total_checks > 0 else 0

    # Email template with compact table summary
    email_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
            .header {{ text-align: center; padding-bottom: 20px; }}
            
            /* Compact Summary Table */
            .summary-table {{
                width: 100%;
                border-collapse: collapse;
                margin: 15px 0;
                background: #f8f9fa;
                border-radius: 5px;
                overflow: hidden;
            }}
            .summary-table td {{
                padding: 10px 12px;
                text-align: center;
                border-right: 1px solid #e0e0e0;
                font-size: 14px;
            }}
            .summary-table td:last-child {{ border-right: none; }}
            .summary-table .stat-value {{
                font-weight: bold;
                font-size: 16px;
            }}
            .total-stat .stat-value {{ color: #495057; }}
            .success-stat .stat-value {{ color: #28a745; }}
            .failed-stat .stat-value {{ color: #dc3545; }}
            .skipped-stat .stat-value {{ color: #ffc107; }}
            .rate-stat .stat-value {{ color: { '#28a745' if success_rate >= 90 else '#ffc107' if success_rate >= 70 else '#dc3545' }; }}
            
            /* Results Section */
            .result-container {{ 
                background: #f9f9f9; 
                border-radius: 5px; 
                padding: 15px; 
                margin: 15px 0;
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
            .success {{ color: #28a745; }}
            .failed {{ color: #dc3545; }}
            .skipped {{ color: #ffc107; }}
            
            /* Status Banner */
            .status-banner {{ 
                padding: 12px; 
                text-align: center; 
                font-size: 16px; 
                font-weight: bold; 
                border-radius: 5px;
                margin: 15px 0;
                background-color: {'#d4edda' if success else '#f8d7da'};
                color: {'#155724' if success else '#721c24'};
            }}
            
            /* Footer */
            .footer {{ 
                margin-top: 20px; 
                padding-top: 15px; 
                border-top: 1px solid #eaeaea;
                font-size: 13px;
                color: #6c757d;
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
            
            <!-- Compact One-Line Summary Table -->
            <table class="summary-table">
                <tr>
                    <td class="total-stat">
                        <div class="stat-value">{total_checks}</div>
                        <div>Total</div>
                    </td>
                    <td class="success-stat">
                        <div class="stat-value">{success_count}</div>
                        <div>Passed</div>
                    </td>
                    <td class="failed-stat">
                        <div class="stat-value">{failed_count}</div>
                        <div>Failed</div>
                    </td>
                    <td class="skipped-stat">
                        <div class="stat-value">{skipped_count}</div>
                        <div>Skipped</div>
                    </td>
                    <td class="rate-stat">
                        <div class="stat-value">{success_rate:.1f}%</div>
                        <div>Success Rate</div>
                    </td>
                </tr>
            </table>
            
            <!-- Detailed Results -->
            <div class="result-container">
                <h3>Detailed Results:</h3>
    """

    # Add validation results
    for i, (result, status) in enumerate(validation_results, 1):
        status_class = "success" if status == "Success" else "failed" if status == "Failed" else "skipped"
        email_body += f"""
        <div class="result-item">
            <div class="result-index">{i}.</div>
            <div><span class="{status_class}">[{status}]</span> {result}</div>
        </div>
        """

    # Add status banner
    email_body += f"""
            </div>
            <div class="status-banner">
                {'✅ All checks passed successfully' if success else '❌ Validation completed with failures'}
            </div>
            
            <div class="footer">
                <p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p>This is an automated message - please do not reply directly</p>
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
