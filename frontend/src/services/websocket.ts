type EventCallback = (event: any) => void;

export class RealtimeWebSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private subscribers: Set<EventCallback> = new Set();
  private reconnectInterval: number = 3000;
  private maxReconnectInterval: number = 30000;
  private shouldReconnect: boolean = true;
  private reconnectTimer: any = null;
  private isConnected: boolean = false;
  private connectionListeners: Set<(connected: boolean) => void> = new Set();

  constructor() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    // In production or via proxy, /ws routes to backend
    this.url = `${protocol}//${host}/ws`;
  }

  public connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.isConnected = true;
        this.reconnectInterval = 3000;
        this.notifyConnectionState(true);
        // Send initial ping
        this.send({ type: 'ping' });
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.subscribers.forEach((cb) => cb(data));
        } catch (err) {
          console.debug('Failed to parse WS message:', event.data);
        }
      };

      this.ws.onclose = () => {
        this.isConnected = false;
        this.notifyConnectionState(false);
        if (this.shouldReconnect) {
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = (err) => {
        console.debug('WebSocket connection error:', err);
        this.ws?.close();
      };
    } catch (err) {
      console.debug('WebSocket initiation error:', err);
      this.scheduleReconnect();
    }
  }

  public subscribe(callback: EventCallback): () => void {
    this.subscribers.add(callback);
    return () => {
      this.subscribers.delete(callback);
    };
  }

  public onConnectionChange(listener: (connected: boolean) => void): () => void {
    this.connectionListeners.add(listener);
    listener(this.isConnected);
    return () => {
      this.connectionListeners.delete(listener);
    };
  }

  public send(data: any): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(typeof data === 'string' ? data : JSON.stringify(data));
    }
  }

  public disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    if (this.ws) {
      this.ws.close();
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectInterval = Math.min(this.reconnectInterval * 1.5, this.maxReconnectInterval);
      this.connect();
    }, this.reconnectInterval);
  }

  private notifyConnectionState(connected: boolean): void {
    this.connectionListeners.forEach((fn) => fn(connected));
  }
}

export const realtimeWS = new RealtimeWebSocket();
