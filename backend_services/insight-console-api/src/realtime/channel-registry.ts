/**
 * Shared upstream polling with fan-out to many subscribers.
 *
 * WHY
 * The console polls from the browser: 14 points, the worst being
 * `operational-command-center` at 8 requests every 10s — PER OPEN TAB.
 * Three operators with two tabs each means the platform absorbs six
 * times the same load, and every one of those requests also re-resolves
 * the session at the Gateway.
 *
 * A channel polls its upstream ONCE per interval regardless of how many
 * subscribers are attached, and pushes the result to all of them. Cost
 * becomes independent of the number of tabs.
 *
 * It also stops polling entirely when the last subscriber leaves — an
 * idle console must not keep generating load, which a client-side
 * `setInterval` cannot guarantee (a backgrounded tab keeps firing).
 */
export type ChannelPayload = Record<string, unknown>;
export type Subscriber = (event: ChannelEvent) => void;

export interface ChannelEvent {
  readonly channel: string;
  /** Poll result, or null when the poll failed. */
  readonly data: ChannelPayload | null;
  /** Present only on failure — subscribers render degraded, not blank. */
  readonly error: string | null;
  readonly at: string;
}

export interface ChannelDefinition {
  readonly name: string;
  /** Resolves this channel's current payload. Called once per tick. */
  readonly poll: () => Promise<ChannelPayload>;
}

export class Channel {
  private readonly subscribers = new Set<Subscriber>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private last: ChannelEvent | null = null;
  private polling = false;

  constructor(
    private readonly definition: ChannelDefinition,
    private readonly intervalMs: number,
    private readonly now: () => Date = () => new Date(),
  ) {}

  get name(): string {
    return this.definition.name;
  }

  get subscriberCount(): number {
    return this.subscribers.size;
  }

  get isPolling(): boolean {
    return this.timer !== null;
  }

  /** Attach a subscriber. Returns the unsubscribe function. */
  subscribe(subscriber: Subscriber): () => void {
    this.subscribers.add(subscriber);

    // A joiner gets the last known value immediately instead of waiting
    // a whole interval to see anything.
    if (this.last !== null) {
      subscriber(this.last);
    }
    if (this.timer === null) {
      this.start();
    }
    return () => this.unsubscribe(subscriber);
  }

  private unsubscribe(subscriber: Subscriber): void {
    this.subscribers.delete(subscriber);
    if (this.subscribers.size === 0) {
      this.stop();
    }
  }

  private start(): void {
    void this.tick();
    this.timer = setInterval(() => void this.tick(), this.intervalMs);
    // Never hold the process open just to poll.
    this.timer.unref?.();
  }

  stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    // Drop the cached value: a channel restarted after an idle gap must
    // not hand a joiner data from minutes ago as if it were current.
    this.last = null;
  }

  private async tick(): Promise<void> {
    // A slow upstream must not stack overlapping polls.
    if (this.polling) return;
    this.polling = true;
    try {
      const data = await this.definition.poll();
      this.emit({
        channel: this.name,
        data,
        error: null,
        at: this.now().toISOString(),
      });
    } catch (error) {
      this.emit({
        channel: this.name,
        data: null,
        error: error instanceof Error ? error.message : 'poll failed',
        at: this.now().toISOString(),
      });
    } finally {
      this.polling = false;
    }
  }

  private emit(event: ChannelEvent): void {
    this.last = event;
    for (const subscriber of [...this.subscribers]) {
      try {
        subscriber(event);
      } catch {
        // One broken subscriber (e.g. a closed socket mid-write) must
        // never stop the others from receiving the tick.
        this.subscribers.delete(subscriber);
      }
    }
  }
}

export class ChannelRegistry {
  private readonly channels = new Map<string, Channel>();

  constructor(
    private readonly intervalMs: number,
    private readonly now: () => Date = () => new Date(),
  ) {}

  register(definition: ChannelDefinition): Channel {
    const existing = this.channels.get(definition.name);
    if (existing) return existing;
    const channel = new Channel(definition, this.intervalMs, this.now);
    this.channels.set(definition.name, channel);
    return channel;
  }

  get(name: string): Channel | undefined {
    return this.channels.get(name);
  }

  names(): string[] {
    return [...this.channels.keys()].sort();
  }

  /** Stop every channel — used on application shutdown. */
  stopAll(): void {
    for (const channel of this.channels.values()) {
      channel.stop();
    }
  }
}
