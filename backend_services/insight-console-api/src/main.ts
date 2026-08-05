import 'reflect-metadata';

import { Logger } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import {
  FastifyAdapter,
  NestFastifyApplication,
} from '@nestjs/platform-fastify';

import { AppModule } from './app.module';
import { loadConfig } from './config/config';

async function bootstrap(): Promise<void> {
  // Validate configuration BEFORE building the app: a missing signing
  // secret must stop the process, not yield a service that rejects
  // every request at runtime.
  const config = loadConfig();

  const app = await NestFactory.create<NestFastifyApplication>(
    AppModule,
    new FastifyAdapter({ trustProxy: true }),
  );
  app.enableShutdownHooks();

  await app.listen(config.PORT, config.HOST);
  new Logger('bootstrap').log(
    `insight-console-api listening on ${config.HOST}:${config.PORT}`,
  );
}

void bootstrap();
