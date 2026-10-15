import { useState } from "react"
import type { MediaPublic } from "@/client"

export function EventImage({
  media,
}: {
  media: MediaPublic
}): React.JSX.Element {
  return (
    <ImageWindow key={`${media.url}:${media.fallback_url}`} media={media} />
  )
}

function ImageWindow({ media }: { media: MediaPublic }): React.JSX.Element {
  const [asset, setAsset] = useState<"primary" | "fallback" | "placeholder">(
    "primary",
  )
  return (
    <figure className="event-image">
      <div className="event-image-window">
        {asset === "placeholder" ? (
          <div
            className="event-image-placeholder"
            role="img"
            aria-label={`Image unavailable: ${media.alt_text}`}
          >
            <span aria-hidden="true">◇</span>
            <span>Image unavailable</span>
            <small>{media.alt_text}</small>
          </div>
        ) : (
          <img
            src={mediaURL(asset === "primary" ? media.url : media.fallback_url)}
            alt={media.alt_text}
            style={{ objectFit: media.fit === "contain" ? "contain" : "cover" }}
            onError={() =>
              setAsset(
                asset === "primary" && media.fallback_url !== media.url
                  ? "fallback"
                  : "placeholder",
              )
            }
            draggable={false}
          />
        )}
      </div>
    </figure>
  )
}

// Root-relative public assets belong to the API origin, not a separate SPA host.
// Keep the opaque path (and any signed query string) exactly as provided.
function mediaURL(url: string): string {
  return url.startsWith("/") && !url.startsWith("//")
    ? `${new URL(import.meta.env.VITE_API_URL || window.location.origin).origin}${url}`
    : url
}
