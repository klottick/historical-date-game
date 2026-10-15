import { isAxiosError } from "axios"

export function extractErrorMessage(err: Error): string {
  const errDetail = isAxiosError(err) ? err.response?.data?.detail : undefined
  if (Array.isArray(errDetail) && typeof errDetail[0]?.msg === "string") {
    return errDetail[0].msg
  }
  if (typeof errDetail === "object" && typeof errDetail?.message === "string") {
    return errDetail.message
  }
  return (
    (typeof errDetail === "string" && errDetail) ||
    err.message ||
    "Something went wrong."
  )
}

export const handleError = function (this: (msg: string) => void, err: Error) {
  const errorMessage = extractErrorMessage(err)
  this(errorMessage)
}

export const getInitials = (name: string): string => {
  return name
    .split(" ")
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase()
}
