"use strict";

const serverless = require("serverless-http");
const { createApp } = require("./dist/server");

const app = createApp();

exports.main_handler = serverless(app);
