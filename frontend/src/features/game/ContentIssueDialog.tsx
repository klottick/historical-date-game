import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"

export function ContentIssueDialog({
  runId,
  eventId,
}: {
  runId: string
  eventId: string
}): React.JSX.Element {
  const [copied, setCopied] = useState(false)
  const email = import.meta.env.VITE_FEEDBACK_EMAIL?.trim()
  // Only public identifiers; no auth, account information, pending years or seed.
  const report = `Historical Date Game content issue\nRun ID: ${runId}\nEvent ID: ${eventId}\n\nDescribe the issue and any source that supports a correction:\n`
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline">Report content issue</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>Report a content issue</DialogTitle>
        <DialogDescription>
          Include these IDs and describe the problem with the prompt, date,
          source or image. Do not include your password or login token.
        </DialogDescription>
        <label htmlFor={`report-${eventId}`}>
          Report details (select to copy)
        </label>
        <textarea
          id={`report-${eventId}`}
          readOnly
          value={report}
          rows={7}
          className="w-full rounded border p-2"
        />
        <Button
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(report)
              setCopied(true)
            } catch {
              setCopied(false)
            }
          }}
        >
          Copy report IDs
        </Button>
        <p role="status">
          {copied
            ? "Report IDs copied."
            : "You can select and copy the details above."}
        </p>
        {email ? (
          <a
            className="underline"
            href={`mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent("Historical Date Game content issue")}&body=${encodeURIComponent(report)}`}
          >
            Email report
          </a>
        ) : (
          <p>
            No feedback email is configured yet. Send the copied IDs and your
            description to the beta host through the channel where you received
            your invitation.
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}
