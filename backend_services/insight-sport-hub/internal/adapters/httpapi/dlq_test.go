package httpapi

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/google/uuid"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

type replayedReader struct {
	record ports.DeadLetterRecord
	marks  int
}

func (r *replayedReader) List(context.Context, ports.DeadLetterQuery) ([]ports.DeadLetterRecord, error) {
	return []ports.DeadLetterRecord{r.record}, nil
}
func (r *replayedReader) Get(context.Context, string) (ports.DeadLetterRecord, error) {
	return r.record, nil
}
func (r *replayedReader) MarkReplayed(context.Context, string, time.Time) error {
	r.marks++
	return nil
}

type countingEnqueuer struct{ count int }

func (e *countingEnqueuer) Enqueue(context.Context, syncdom.SyncJob) error {
	e.count++
	return nil
}

func TestDLQReplayIsIdempotentAfterOriginalWasReplayed(t *testing.T) {
	replayedAt := time.Now().UTC()
	id := uuid.NewString()
	reader := &replayedReader{record: ports.DeadLetterRecord{
		ID: id, ReplayedAt: &replayedAt,
	}}
	enqueuer := &countingEnqueuer{}
	handler := DLQReplayHandler(DLQConfig{Reader: reader, Enqueuer: enqueuer})
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(
		recorder,
		httptest.NewRequest(http.MethodPost, "/v1/dlq/"+id+"/replay", nil),
	)
	if recorder.Code != http.StatusOK || enqueuer.count != 0 || reader.marks != 0 {
		t.Fatalf("status=%d enqueues=%d marks=%d", recorder.Code, enqueuer.count, reader.marks)
	}
}

func TestDLQOpsTokenFailsClosed(t *testing.T) {
	next := http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Fatal("disabled DLQ handler reached")
	})
	recorder := httptest.NewRecorder()
	requireOpsToken("", next).ServeHTTP(
		recorder, httptest.NewRequest(http.MethodGet, "/v1/dlq", nil),
	)
	if recorder.Code != http.StatusServiceUnavailable {
		t.Fatalf("status=%d", recorder.Code)
	}
}
