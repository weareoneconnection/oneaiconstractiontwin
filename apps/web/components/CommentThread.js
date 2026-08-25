"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { since } from "../lib/format";
import { roleLabel, useSession } from "../lib/session";
import { Badge, EmptyState, PermissionButton, Skeleton } from "./ui";
import { useToast } from "./ui/Toast";

/**
 * Discussion attached to a project or to something inside it.
 *
 * This is where judgement lives that the data cannot hold: why an activity really
 * slipped, whether an AI recommendation is sound. Resolving keeps the history instead
 * of deleting it, and both actions are recorded in the audit chain.
 */
export default function CommentThread({ projectId, targetType = "project", targetId = "", title = "Discussion", compact = false }) {
  const { can, me } = useSession();
  const { notify } = useToast();
  const [comments, setComments] = useState(null);
  const [body, setBody] = useState("");
  const [replyTo, setReplyTo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showResolved, setShowResolved] = useState(false);

  const load = async () => {
    const params = new URLSearchParams({ target_type: targetType, include_resolved: "true" });
    if (targetId) params.set("target_id", targetId);
    setComments(await api(`/api/v1/projects/${projectId}/comments?${params}`));
  };

  useEffect(() => { load().catch(error => notify(error.message, "error")); }, [projectId, targetType, targetId]);

  const submit = async event => {
    event.preventDefault();
    if (!body.trim()) return;
    setBusy(true);
    try {
      await api(`/api/v1/projects/${projectId}/comments`, {
        method: "POST",
        body: JSON.stringify({ body, target_type: targetType, target_id: targetId, parent_id: replyTo }),
      });
      setBody("");
      setReplyTo(null);
      await load();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const setResolved = async (comment, resolved) => {
    try {
      await api(`/api/v1/projects/${projectId}/comments/${comment.id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ resolved }),
      });
      await load();
      notify(resolved ? "Thread resolved" : "Thread reopened", "success");
    } catch (error) {
      notify(error.message, "error");
    }
  };

  const roots = (comments || []).filter(comment => !comment.parent_id && (showResolved || !comment.resolved));
  const repliesOf = id => (comments || []).filter(comment => comment.parent_id === id);
  const hiddenResolved = (comments || []).filter(comment => !comment.parent_id && comment.resolved).length;

  return (
    <div className={`comment-thread ${compact ? "compact" : ""}`}>
      <div className="thread-head">
        <b>{title}</b>
        <div className="thread-actions">
          {hiddenResolved > 0 && (
            <button className="btn ghost" onClick={() => setShowResolved(value => !value)}>
              {showResolved ? "Hide resolved" : `Show ${hiddenResolved} resolved`}
            </button>
          )}
        </div>
      </div>

      {!comments && <Skeleton lines={2} />}
      {comments && roots.length === 0 && (
        <EmptyState
          title="No discussion yet"
          description="Record the judgement behind the numbers: why something slipped, or whether a recommendation should be accepted."
        />
      )}

      {roots.map(comment => (
        <div key={comment.id} className={`comment ${comment.resolved ? "resolved" : ""}`}>
          <div className="comment-head">
            <span className="comment-author">{comment.author_email || comment.author_id}</span>
            <Badge tone="neutral">{roleLabel(comment.author_role)}</Badge>
            <span className="comment-time">{since(comment.created_at)}</span>
            {comment.resolved && <Badge tone="good">resolved</Badge>}
          </div>
          <p>{comment.body}</p>
          <div className="comment-tools">
            <PermissionButton allowed={can("comment:write")} permission="comment:write" className="btn ghost" onClick={() => setReplyTo(comment.id)}>
              Reply
            </PermissionButton>
            <PermissionButton
              allowed={can("comment:write")}
              permission="comment:write"
              className="btn ghost"
              onClick={() => setResolved(comment, !comment.resolved)}
            >
              {comment.resolved ? "Reopen" : "Resolve"}
            </PermissionButton>
          </div>
          {repliesOf(comment.id).map(reply => (
            <div key={reply.id} className="comment reply">
              <div className="comment-head">
                <span className="comment-author">{reply.author_email || reply.author_id}</span>
                <Badge tone="neutral">{roleLabel(reply.author_role)}</Badge>
                <span className="comment-time">{since(reply.created_at)}</span>
              </div>
              <p>{reply.body}</p>
            </div>
          ))}
        </div>
      ))}

      <form className="comment-form" onSubmit={submit}>
        {replyTo && (
          <div className="reply-banner">
            Replying in thread
            <button type="button" className="btn ghost" onClick={() => setReplyTo(null)}>Cancel</button>
          </div>
        )}
        <textarea
          rows={compact ? 2 : 3}
          placeholder={can("comment:write") ? "Add a note for the team…" : "Your role cannot post comments"}
          value={body}
          onChange={event => setBody(event.target.value)}
          disabled={!can("comment:write")}
        />
        <div className="comment-form-foot">
          <small>Posting as {me?.user_id || "—"} · {roleLabel(me?.role)}</small>
          <PermissionButton allowed={can("comment:write")} permission="comment:write" className="btn primary" type="submit" disabled={busy || !body.trim()}>
            {busy ? "Posting…" : replyTo ? "Post reply" : "Post comment"}
          </PermissionButton>
        </div>
      </form>
    </div>
  );
}
