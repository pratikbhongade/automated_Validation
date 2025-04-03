// static/js/htmlReport.js
class HTMLReportGenerator {
  constructor() {
    this.screenshots = [];
    this.performanceData = null;
    this.validationResults = null;
  }

  addScreenshot(name, dataUrl) {
    this.screenshots.push({
      name,
      dataUrl,
      timestamp: new Date().toISOString()
    });
  }

  setPerformanceData(data) {
    this.performanceData = data;
  }

  setValidationResults(results) {
    this.validationResults = results;
  }

  generateReportHTML() {
    // This would be replaced with actual template rendering
    return `
      <!DOCTYPE html>
      <html>
      <head>
        <title>Validation Report</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
          .report-section { margin-bottom: 40px; }
          .screenshot-thumbnail { 
            cursor: pointer; 
            transition: transform 0.2s;
            margin: 5px;
          }
          .screenshot-thumbnail:hover { transform: scale(1.05); }
          .modal-image { max-width: 100%; }
        </style>
      </head>
      <body>
        <div class="container mt-4">
          <h1 class="text-center mb-4">Validation Report</h1>
          
          <div class="report-section">
            <h2>Validation Summary</h2>
            <div class="row">
              <div class="col-md-6">
                <canvas id="summaryChart"></canvas>
              </div>
              <div class="col-md-6">
                <table class="table table-bordered">
                  <tr><th>Total Checks</th><td>${this.validationResults.total}</td></tr>
                  <tr><th>Successful</th><td>${this.validationResults.successful}</td></tr>
                  <tr><th>Failed</th><td>${this.validationResults.failed}</td></tr>
                  <tr><th>Skipped</th><td>${this.validationResults.skipped}</td></tr>
                </table>
              </div>
            </div>
          </div>
          
          <div class="report-section">
            <h2>Performance Metrics</h2>
            <div class="row">
              <div class="col-md-6">
                <h4>Component Load Times</h4>
                <canvas id="componentLoadChart"></canvas>
              </div>
              <div class="col-md-6">
                <h4>Interaction Times</h4>
                <canvas id="interactionChart"></canvas>
              </div>
            </div>
          </div>
          
          <div class="report-section">
            <h2>Screenshots</h2>
            <div class="screenshot-gallery">
              ${this.screenshots.map(s => `
                <img src="${s.dataUrl}" 
                     class="screenshot-thumbnail img-thumbnail" 
                     width="200" 
                     data-bs-toggle="modal" 
                     data-bs-target="#screenshotModal"
                     onclick="document.getElementById('modalImage').src='${s.dataUrl}'">
              `).join('')}
            </div>
          </div>
          
          <!-- Screenshot Modal -->
          <div class="modal fade" id="screenshotModal" tabindex="-1">
            <div class="modal-dialog modal-xl">
              <div class="modal-content">
                <div class="modal-body text-center">
                  <img id="modalImage" class="modal-image">
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <script>
          // Initialize charts
          document.addEventListener('DOMContentLoaded', function() {
            // Summary Chart
            new Chart(document.getElementById('summaryChart'), {
              type: 'doughnut',
              data: {
                labels: ['Success', 'Failed', 'Skipped'],
                datasets: [{
                  data: [
                    ${this.validationResults.successful},
                    ${this.validationResults.failed},
                    ${this.validationResults.skipped}
                  ],
                  backgroundColor: ['#28a745', '#dc3545', '#ffc107']
                }]
              }
            });
            
            // Performance Charts would be initialized here
          });
        </script>
      </body>
      </html>
    `;
  }

  downloadReport() {
    const html = this.generateReportHTML();
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `validation_report_${new Date().toISOString().slice(0,10)}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = HTMLReportGenerator;
} else {
  window.HTMLReportGenerator = HTMLReportGenerator;
}
