export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t py-4 px-6">
      <div className="flex flex-col items-center justify-between gap-4 sm:flex-row">
        <p className="text-muted-foreground text-sm">
          Historical Date Game · {currentYear}
        </p>
        <p className="text-sm text-muted-foreground">
          Event sources and media credits accompany each revealed card.
        </p>
      </div>
    </footer>
  )
}
