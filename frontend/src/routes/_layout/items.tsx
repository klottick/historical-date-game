import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Search } from "lucide-react"
import { Suspense, useSyncExternalStore } from "react"

import { ItemsService } from "@/client"
import { DataTable } from "@/components/Common/DataTable"
import AddItem from "@/components/Items/AddItem"
import { columns } from "@/components/Items/columns"
import PendingItems from "@/components/Pending/PendingItems"
import {
  accountToken,
  sessionError,
  subscribeAccountChange,
} from "@/features/game/identityState"
import { requireAccount } from "@/hooks/useAuth"

function getItemsQueryOptions(token: string) {
  return {
    queryFn: async ({ signal }: { signal: AbortSignal }) => {
      const assertAccount = () => {
        if (token !== accountToken())
          throw sessionError("game_identity_changed", "Account changed")
      }
      const result = (
        await ItemsService.readItems({
          auth: token,
          signal,
          requestValidator: async () => assertAccount(),
          query: { skip: 0, limit: 100 },
          throwOnError: true,
        })
      ).data
      assertAccount()
      return result
    },
    queryKey: ["items", token],
  }
}

export const Route = createFileRoute("/_layout/items")({
  beforeLoad: () => requireAccount(),
  component: Items,
  head: () => ({
    meta: [
      {
        title: "Items - FastAPI Cloud",
      },
    ],
  }),
})

function ItemsTableContent() {
  const token = useSyncExternalStore(subscribeAccountChange, accountToken)
  const { data: items } = useSuspenseQuery(getItemsQueryOptions(token))

  if (items.data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center text-center py-12">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Search className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold">You don't have any items yet</h3>
        <p className="text-muted-foreground">Add a new item to get started</p>
      </div>
    )
  }

  return <DataTable columns={columns} data={items.data} />
}

function ItemsTable() {
  return (
    <Suspense fallback={<PendingItems />}>
      <ItemsTableContent />
    </Suspense>
  )
}

function Items() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Items</h1>
          <p className="text-muted-foreground">Create and manage your items</p>
        </div>
        <AddItem />
      </div>
      <ItemsTable />
    </div>
  )
}
