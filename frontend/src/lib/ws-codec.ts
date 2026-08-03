import { create, fromBinary, toBinary } from "@bufbuild/protobuf";

import type { ServiceState } from "@/lib/types";
import {
  ClientMessageSchema,
  EchoSchema,
  PingSchema,
  PresenceSchema,
  RefreshSchema,
  RttSchema,
  ServerMessageSchema,
  type Echo,
  type Hello,
  type ServerMessage,
} from "@/lib/ws_pb";

export type DecodedServer =
  | { type: "hello"; data: Hello }
  | { type: "state"; data: ServiceState }
  | { type: "heartbeat"; rev: number }
  | { type: "error"; detail: string }
  | { type: "pong" }
  | { type: "echo"; echo: Echo }
  | { type: "echo_reply"; echo: Echo };

async function toUint8Array(data: ArrayBuffer | Blob | string): Promise<Uint8Array> {
  if (typeof data === "string") return new TextEncoder().encode(data);
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  if (ArrayBuffer.isView(data)) {
    return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  }
  return new Uint8Array(await data.arrayBuffer());
}

export function decodeServerFrame(raw: Uint8Array): DecodedServer | null {
  let message: ServerMessage;
  try {
    message = fromBinary(ServerMessageSchema, raw);
  } catch {
    return null;
  }
  switch (message.body.case) {
    case "hello":
      return { type: "hello", data: message.body.value };
    case "state": {
      const raw = message.body.value.json;
      if (!raw || raw.length === 0) {
        return { type: "state", data: {} as ServiceState };
      }
      const text = new TextDecoder().decode(raw);
      return { type: "state", data: JSON.parse(text) as ServiceState };
    }
    case "heartbeat":
      return { type: "heartbeat", rev: Number(message.body.value.rev) };
    case "error":
      return { type: "error", detail: message.body.value.detail };
    case "pong":
      return { type: "pong" };
    case "echo": {
      const echo = message.body.value;
      return { type: echo.reply ? "echo_reply" : "echo", echo };
    }
    default:
      return null;
  }
}

export async function decodeServerEvent(data: ArrayBuffer | Blob | string) {
  return decodeServerFrame(await toUint8Array(data));
}

export function encodeRefresh() {
  return toBinary(
    ClientMessageSchema,
    create(ClientMessageSchema, {
      body: { case: "refresh", value: create(RefreshSchema) },
    }),
  );
}

export function encodePing() {
  return toBinary(
    ClientMessageSchema,
    create(ClientMessageSchema, {
      body: { case: "ping", value: create(PingSchema) },
    }),
  );
}

export function encodePresence(patch: { tab?: string; activity?: string }) {
  return toBinary(
    ClientMessageSchema,
    create(ClientMessageSchema, {
      body: {
        case: "presence",
        value: create(PresenceSchema, {
          tab: patch.tab ?? "",
          activity: patch.activity ?? "",
        }),
      },
    }),
  );
}

export function encodeRtt(peerId: string, rttMs: number) {
  return toBinary(
    ClientMessageSchema,
    create(ClientMessageSchema, {
      body: {
        case: "rtt",
        value: create(RttSchema, { peerId, rttMs }),
      },
    }),
  );
}

export function encodeEcho(args: {
  id: string;
  t0: number;
  t1?: number;
  to?: string;
  reply?: boolean;
}) {
  return toBinary(
    ClientMessageSchema,
    create(ClientMessageSchema, {
      body: {
        case: "echo",
        value: create(EchoSchema, {
          id: args.id,
          t0: args.t0,
          t1: args.t1,
          toId: args.to ?? "",
          reply: Boolean(args.reply),
        }),
      },
    }),
  );
}
