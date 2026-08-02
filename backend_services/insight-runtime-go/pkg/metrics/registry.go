// Package metrics gives every service a Prometheus registry preloaded
// with the standard process + Go collectors plus an HTTP handler.
//
// Services that need custom metrics:
//
//	type myService struct {
//	    requestsTotal prometheus.Counter
//	}
//	func New(reg prometheus.Registerer) *myService {
//	    return &myService{
//	        requestsTotal: promauto.With(reg).NewCounter(prometheus.CounterOpts{
//	            Name: "myservice_requests_total",
//	            Help: "...",
//	        }),
//	    }
//	}
package metrics

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// Bundle is the per-service metrics surface — registry plus the http
// handler that exposes `/metrics`.
type Bundle struct {
	Registry *prometheus.Registry
	Handler  http.Handler
}

// New returns a fresh Bundle with the standard process + Go runtime
// collectors registered. Service-specific metrics register against
// `Bundle.Registry`.
func New() *Bundle {
	reg := prometheus.NewRegistry()
	reg.MustRegister(
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}),
		collectors.NewGoCollector(),
	)
	return &Bundle{
		Registry: reg,
		Handler: promhttp.HandlerFor(reg, promhttp.HandlerOpts{
			EnableOpenMetrics: true,
		}),
	}
}
