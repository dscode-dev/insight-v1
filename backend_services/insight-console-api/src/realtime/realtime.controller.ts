import {
  Controller,
  Get,
  NotFoundException,
  Param,
  Req,
  Res,
} from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';

import { RealtimeService } from './realtime.service';

/**
 * Server-Sent Events. SSE rather than WebSocket because the console's
 * need is strictly server→client fan-out: no client messages, and SSE
 * reconnects on its own through any ordinary HTTP proxy.
 */
@Controller('realtime')
export class RealtimeController {
  constructor(private readonly realtime: RealtimeService) {}

  @Get('channels')
  list(): { channels: string[] } {
    return { channels: this.realtime.channels() };
  }

  @Get('channels/:name')
  stream(
    @Param('name') name: string,
    @Req() request: FastifyRequest,
    @Res() reply: FastifyReply,
  ): void {
    const channel = this.realtime.channel(name);
    if (!channel) {
      throw new NotFoundException(`unknown realtime channel: ${name}`);
    }

    reply.raw.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      // Proxies that buffer would defeat the entire point.
      'X-Accel-Buffering': 'no',
    });

    const unsubscribe = channel.subscribe((event) => {
      reply.raw.write(`event: ${event.channel}\n`);
      reply.raw.write(`data: ${JSON.stringify(event)}\n\n`);
    });

    // Unsubscribing on close is what lets an idle channel stop polling
    // entirely — without it the fan-out would keep running forever.
    const close = (): void => {
      unsubscribe();
      reply.raw.end();
    };
    request.raw.on('close', close);
    request.raw.on('error', close);
  }
}
