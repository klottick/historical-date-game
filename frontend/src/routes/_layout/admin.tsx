import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Suspense } from "react"

import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { DataTable } from "@/components/Common/DataTable"
import PendingUsers from "@/components/Pending/PendingUsers"
import { accountToken, sessionError } from "@/features/game/identityState"
import useAuth, { requireAccount } from "@/hooks/useAuth"

function getUsersQueryOptions(token: string) {
  return {
    queryFn: async ({ signal }: { signal: AbortSignal }) => {
      const assertAccount = () => {
        if (token !== accountToken())
          throw sessionError("game_identity_changed", "Account changed")
      }
      const result = (
        await UsersService.readUsers({
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
    queryKey: ["users", token],
  }
}

export const Route = createFileRoute("/_layout/admin")({
  beforeLoad: () => requireAccount(true),
  component: Admin,
  head: () => ({
    meta: [
      {
        title: "Admin - FastAPI Cloud",
      },
    ],
  }),
})

function UsersTableContent() {
  const { user: currentUser } = useAuth()
  const { data: users } = useSuspenseQuery(getUsersQueryOptions(accountToken()))

  const tableData: UserTableData[] = users.data.map((user: UserPublic) => ({
    ...user,
    isCurrentUser: currentUser?.id === user.id,
  }))

  return <DataTable columns={columns} data={tableData} />
}

function UsersTable() {
  return (
    <Suspense fallback={<PendingUsers />}>
      <UsersTableContent />
    </Suspense>
  )
}

function Admin() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Users</h1>
          <p className="text-muted-foreground">
            Manage user accounts and permissions
          </p>
        </div>
        <AddUser />
      </div>
      <UsersTable />
    </div>
  )
}
