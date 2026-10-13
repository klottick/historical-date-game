import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { redirect, useNavigate } from "@tanstack/react-router"
import { isAxiosError } from "axios"
import { useSyncExternalStore } from "react"

import {
  type BodyLoginLoginAccessToken as AccessToken,
  LoginService,
  type UserPublic,
  type UserRegister,
  UsersService,
} from "@/client"
import {
  accountToken,
  notifyAccountChange,
  sessionError,
  subscribeAccountChange,
} from "@/features/game/identityState"
import { handleError } from "@/utils"
import useCustomToast from "./useCustomToast"

const isLoggedIn = () => {
  return !!accountToken()
}

export async function requireAccount(admin = false) {
  const token = accountToken()
  if (!token) throw redirect({ to: "/login" })
  let user: UserPublic
  try {
    user = (await UsersService.readUserMe({ auth: token, throwOnError: true }))
      .data
  } catch (error) {
    if (token !== accountToken()) throw redirect({ to: "/" })
    if (
      isAxiosError(error) &&
      [401, 403].includes(error.response?.status ?? 0)
    ) {
      localStorage.removeItem("access_token")
      notifyAccountChange()
    }
    throw redirect({ to: "/login" })
  }
  if (token !== accountToken()) throw redirect({ to: "/login" })
  if (admin && !user.is_superuser) throw redirect({ to: "/" })
}

const useAuth = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()
  const token = useSyncExternalStore(subscribeAccountChange, accountToken)

  const { data: user } = useQuery<UserPublic | null, Error>({
    queryKey: ["currentUser", token],
    queryFn: async ({ signal }) => {
      const result = (
        await UsersService.readUserMe({
          auth: token,
          signal,
          throwOnError: true,
        })
      ).data
      if (token !== accountToken())
        throw sessionError("game_identity_changed", "Account changed")
      return result
    },
    enabled: !!token,
    retry: (count, error) =>
      !(
        isAxiosError(error) && [401, 403].includes(error.response?.status ?? 0)
      ) && count < 3,
  })

  const signUpMutation = useMutation({
    mutationFn: (data: UserRegister) =>
      UsersService.registerUser({ body: data, throwOnError: true }),
    onSuccess: () => {
      navigate({ to: "/login" })
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const login = async (data: AccessToken) => {
    const previousToken = accountToken()
    const response = await LoginService.loginAccessToken({
      body: data,
      throwOnError: true,
    })
    if (previousToken !== accountToken())
      throw sessionError(
        "game_identity_changed",
        "Account changed while signing in. Sign in again only if you want to switch players.",
      )
    localStorage.setItem("access_token", response.data.access_token)
    notifyAccountChange()
    return response.data.access_token
  }

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: (confirmedToken) => {
      if (confirmedToken !== accountToken()) return
      const returnTo = sessionStorage.getItem("game-login-return")
      sessionStorage.removeItem("game-login-return")
      queryClient.clear()
      const runId = returnTo?.match(/^\/play\/([\da-f-]+)$/)?.[1]
      if (runId) navigate({ to: "/play/$runId", params: { runId } })
      else navigate({ to: "/" })
    },
    onError: handleError.bind(showErrorToast),
  })

  const logout = () => {
    localStorage.removeItem("access_token")
    notifyAccountChange()
    queryClient.cancelQueries()
    queryClient.clear()
    navigate({ to: "/" })
  }

  return {
    signUpMutation,
    loginMutation,
    logout,
    user: token ? user : undefined,
  }
}

export { isLoggedIn }
export default useAuth
