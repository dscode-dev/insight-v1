import { Channel, ChannelEvent, ChannelRegistry } from './channel-registry';

const INTERVAL = 1000;

describe('Channel', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  function channel(poll: () => Promise<Record<string, unknown>>) {
    return new Channel({ name: 'test', poll }, INTERVAL);
  }

  it('polls once and fans out to every subscriber', async () => {
    const poll = jest.fn().mockResolvedValue({ value: 1 });
    const subject = channel(poll);
    const a: ChannelEvent[] = [];
    const b: ChannelEvent[] = [];

    subject.subscribe((event) => a.push(event));
    subject.subscribe((event) => b.push(event));
    await jest.advanceTimersByTimeAsync(0);

    // THE point of the design: two subscribers, one upstream call.
    expect(poll).toHaveBeenCalledTimes(1);
    expect(a.at(-1)?.data).toEqual({ value: 1 });
    expect(b.at(-1)?.data).toEqual({ value: 1 });
  });

  it('does not multiply upstream load per subscriber over time', async () => {
    const poll = jest.fn().mockResolvedValue({ ok: true });
    const subject = channel(poll);
    for (let i = 0; i < 5; i += 1) subject.subscribe(() => undefined);

    await jest.advanceTimersByTimeAsync(0);
    await jest.advanceTimersByTimeAsync(INTERVAL * 3);

    // 1 immediate + 3 ticks = 4, regardless of the 5 subscribers.
    expect(poll).toHaveBeenCalledTimes(4);
  });

  it('replays the last value to a late joiner immediately', async () => {
    const poll = jest.fn().mockResolvedValue({ value: 7 });
    const subject = channel(poll);
    subject.subscribe(() => undefined);
    await jest.advanceTimersByTimeAsync(0);

    const late: ChannelEvent[] = [];
    subject.subscribe((event) => late.push(event));

    // No waiting a full interval to render something.
    expect(late).toHaveLength(1);
    expect(late[0].data).toEqual({ value: 7 });
  });

  it('stops polling when the last subscriber leaves', async () => {
    const poll = jest.fn().mockResolvedValue({});
    const subject = channel(poll);
    const unsubscribe = subject.subscribe(() => undefined);
    await jest.advanceTimersByTimeAsync(0);
    expect(subject.isPolling).toBe(true);

    unsubscribe();

    expect(subject.isPolling).toBe(false);
    poll.mockClear();
    await jest.advanceTimersByTimeAsync(INTERVAL * 5);
    // An idle console must generate zero upstream load.
    expect(poll).not.toHaveBeenCalled();
  });

  it('keeps polling while at least one subscriber remains', async () => {
    const subject = channel(jest.fn().mockResolvedValue({}));
    const first = subject.subscribe(() => undefined);
    subject.subscribe(() => undefined);

    first();

    expect(subject.isPolling).toBe(true);
    expect(subject.subscriberCount).toBe(1);
  });

  it('does not replay stale data after an idle restart', async () => {
    const poll = jest.fn().mockResolvedValue({ value: 1 });
    const subject = channel(poll);
    const unsubscribe = subject.subscribe(() => undefined);
    await jest.advanceTimersByTimeAsync(0);
    unsubscribe();

    const events: ChannelEvent[] = [];
    subject.subscribe((event) => events.push(event));

    // Nothing replayed synchronously — the value from before the idle
    // gap would be presented as current otherwise.
    expect(events).toHaveLength(0);
  });

  it('emits an error event instead of throwing when the poll fails', async () => {
    const poll = jest.fn().mockRejectedValue(new Error('upstream down'));
    const subject = channel(poll);
    const events: ChannelEvent[] = [];

    subject.subscribe((event) => events.push(event));
    await jest.advanceTimersByTimeAsync(0);

    expect(events.at(-1)?.data).toBeNull();
    expect(events.at(-1)?.error).toBe('upstream down');
  });

  it('recovers after a failed poll', async () => {
    const poll = jest
      .fn()
      .mockRejectedValueOnce(new Error('blip'))
      .mockResolvedValue({ value: 2 });
    const subject = channel(poll);
    const events: ChannelEvent[] = [];

    subject.subscribe((event) => events.push(event));
    await jest.advanceTimersByTimeAsync(0);
    await jest.advanceTimersByTimeAsync(INTERVAL);

    expect(events.at(-1)?.error).toBeNull();
    expect(events.at(-1)?.data).toEqual({ value: 2 });
  });

  it('does not stack overlapping polls when upstream is slower than the interval', async () => {
    let release: (value: Record<string, unknown>) => void = () => undefined;
    const poll = jest.fn().mockImplementation(
      () => new Promise<Record<string, unknown>>((resolve) => { release = resolve; }),
    );
    const subject = channel(poll);
    subject.subscribe(() => undefined);

    await jest.advanceTimersByTimeAsync(0);
    await jest.advanceTimersByTimeAsync(INTERVAL * 3);

    // Still exactly one in-flight call — ticks during a slow poll are skipped.
    expect(poll).toHaveBeenCalledTimes(1);
    release({});
  });

  it('drops a subscriber that throws without affecting the others', async () => {
    const subject = channel(jest.fn().mockResolvedValue({ v: 1 }));
    const healthy: ChannelEvent[] = [];
    subject.subscribe(() => {
      throw new Error('socket closed');
    });
    subject.subscribe((event) => healthy.push(event));

    await jest.advanceTimersByTimeAsync(0);
    await jest.advanceTimersByTimeAsync(INTERVAL);

    expect(subject.subscriberCount).toBe(1);
    expect(healthy.length).toBeGreaterThanOrEqual(2);
  });
});

describe('ChannelRegistry', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('returns the same channel for a repeated registration', () => {
    const registry = new ChannelRegistry(INTERVAL);
    const first = registry.register({ name: 'a', poll: async () => ({}) });
    const second = registry.register({ name: 'a', poll: async () => ({}) });

    // Registering twice must not create a second poller for one name.
    expect(second).toBe(first);
    expect(registry.names()).toEqual(['a']);
  });

  it('stopAll halts every channel', async () => {
    const registry = new ChannelRegistry(INTERVAL);
    const poll = jest.fn().mockResolvedValue({});
    const channel = registry.register({ name: 'a', poll });
    channel.subscribe(() => undefined);
    await jest.advanceTimersByTimeAsync(0);

    registry.stopAll();

    expect(channel.isPolling).toBe(false);
  });

  it('get() returns undefined for an unknown channel', () => {
    expect(new ChannelRegistry(INTERVAL).get('nope')).toBeUndefined();
  });
});
