// static/js/performanceMetrics.js
class PerformanceMetrics {
  constructor() {
    this.metrics = {
      interactions: [],
      componentLoadTimes: {},
      elementTimings: {}
    };
    this.currentInteraction = null;
  }

  startInteraction(name) {
    this.currentInteraction = {
      name,
      startTime: performance.now(),
      endTime: null,
      duration: null
    };
    return this.currentInteraction;
  }

  endInteraction() {
    if (this.currentInteraction) {
      this.currentInteraction.endTime = performance.now();
      this.currentInteraction.duration = 
        this.currentInteraction.endTime - this.currentInteraction.startTime;
      this.metrics.interactions.push(this.currentInteraction);
      this.currentInteraction = null;
    }
  }

  recordComponentLoad(componentName, duration) {
    if (!this.metrics.componentLoadTimes[componentName]) {
      this.metrics.componentLoadTimes[componentName] = [];
    }
    this.metrics.componentLoadTimes[componentName].push(duration);
  }

  recordElementTiming(elementName, duration) {
    if (!this.metrics.elementTimings[elementName]) {
      this.metrics.elementTimings[elementName] = [];
    }
    this.metrics.elementTimings[elementName].push(duration);
  }

  getStats(data) {
    if (!data || data.length === 0) return null;
    return {
      min: Math.min(...data),
      max: Math.max(...data),
      avg: data.reduce((a, b) => a + b, 0) / data.length,
      count: data.length
    };
  }

  generatePerformanceReport() {
    const componentStats = {};
    for (const [name, times] of Object.entries(this.metrics.componentLoadTimes)) {
      componentStats[name] = this.getStats(times);
    }

    const elementStats = {};
    for (const [name, times] of Object.entries(this.metrics.elementTimings)) {
      elementStats[name] = this.getStats(times);
    }

    return {
      interactions: this.metrics.interactions,
      componentStats,
      elementStats,
      timestamp: new Date().toISOString()
    };
  }
}

// Export for use in other files
if (typeof module !== 'undefined' && module.exports) {
  module.exports = PerformanceMetrics;
} else {
  window.PerformanceMetrics = PerformanceMetrics;
}
