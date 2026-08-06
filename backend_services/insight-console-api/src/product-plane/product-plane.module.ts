import { Module } from "@nestjs/common";

import { ProductPlaneController } from "./product-plane.controller";

@Module({ controllers: [ProductPlaneController] })
export class ProductPlaneModule {}
