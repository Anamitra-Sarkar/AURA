import type { AuraMessage } from '../types';

function formatTimestamp(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function ChatMessage({ message }: { message: AuraMessage }) {
  return (
    <article className={`message message-${message.role}`}>
      <div className="message-meta">
        <strong>{message.role === 'user' ? 'You' : 'AURA'}</strong>
        <span>{formatTimestamp(message.createdAt)}</span>
      </div>
      <div className="message-body">
        <pre>{message.content}</pre>
      </div>
      {message.details ? (
        <div className="message-details">
          {Object.entries(message.details).map(([key, value]) => (
            <span key={key}>
              {key}: {typeof value === 'string' ? value : JSON.stringify(value)}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  );
}
