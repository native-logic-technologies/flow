import { useState, useEffect, useRef } from 'react';
import { LiveKitRoom } from '@livekit/components-react';
import VoiceOrb from './VoiceOrb';

export default function App() {
  // Use the Cloudflare tunnel URL for local LiveKit
  const url = import.meta.env.VITE_LIVEKIT_URL || "wss://flow.speak.ad";
  
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shouldConnect, setShouldConnect] = useState(false);
  const fetchedRef = useRef(false);

  useEffect(() => {
    // Prevent double-fetch in React Strict Mode
    if (fetchedRef.current) return;
    fetchedRef.current = true;

    const fetchToken = async () => {
      try {
        // For local LiveKit, generate token directly (no backend needed)
        // Or use a simple token endpoint
        const participantName = "user-" + Math.floor(Math.random() * 10000);
        
        // Option 1: Generate token client-side (for testing)
        // This is insecure for production but works for testing
        const apiKey = "APIQp4vjmCjrWQ9";
        const apiSecret = "PcRKzAOUY0zqSM2j2a8VQpFLdMQz3qQD6GwQvOJZf4l";
        
        // Simple JWT generation
        const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
        const now = Math.floor(Date.now() / 1000);
        const payload = btoa(JSON.stringify({
          exp: now + 3600,
          iss: apiKey,
          sub: participantName,
          video: {
            roomJoin: true,
            room: "dgx-spark-room",
            canPublish: true,
            canSubscribe: true,
            canPublishData: true
          }
        }));
        
        // Note: This is a demo token - real implementation needs server-side signing
        const token = `${header}.${payload}.demo`;
        setToken(token);
        
        console.log("Connected to local LiveKit at:", url);
        console.log("Room: dgx-spark-room");
        console.log("Participant:", participantName);
        
      } catch (err) {
        console.error("Error:", err);
        setError("Failed to connect to DGX Spark. Please ensure the tunnel is running.");
      }
    };

    fetchToken();
  }, []);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-black text-red-500">
        <p className="font-light">{error}</p>
        <p className="text-sm mt-4 text-gray-500">
          Make sure cloudflared is running and the local LiveKit is up.
        </p>
      </div>
    );
  }

  if (!token) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-black text-white">
        <p className="animate-pulse font-light">Connecting to DGX Spark...</p>
        <p className="text-sm mt-4 text-gray-500">{url}</p>
      </div>
    );
  }

  // FIX: Only connect after user clicks (prevents 3-track bug + autoplay issues)
  if (!shouldConnect) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-black text-white">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold mb-2">DGX Spark Voice AI</h1>
          <p className="text-gray-400">Comma-Level Chunking • ~650ms latency</p>
          <p className="text-sm text-gray-500 mt-2">Room: dgx-spark-room</p>
        </div>
        <button
          onClick={() => setShouldConnect(true)}
          className="px-8 py-4 bg-cyan-600 hover:bg-cyan-500 rounded-full text-white font-medium transition-colors"
        >
          Start Call with Phil
        </button>
        <p className="text-xs text-gray-600 mt-8">
          Config: FLUSH_SIZE=25, prefill=3, voice=phil
        </p>
      </div>
    );
  }

  return (
    <LiveKitRoom
      serverUrl={url}
      token={token}
      connect={shouldConnect}
      audio={true}
      video={false}
    >
      <div className="flex flex-col items-center justify-center min-h-screen bg-black">
        <div className="w-full max-w-md h-96 flex items-center justify-center">
          <VoiceOrb />
        </div>
        <h1 className="mt-8 text-white text-xl font-light">Talking to Phil (DGX-Accelerated)</h1>
        <p className="text-sm text-gray-500 mt-2">flow.speak.ad • Comma-Level Chunking</p>
      </div>
    </LiveKitRoom>
  );
}
