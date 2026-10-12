import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { isAxiosError } from "axios"

import {
  type BodyLoginLoginAccessToken as AccessToken,
  LoginService,
  type UserPublic,
  type UserRegister,
  UsersService,
} from "@/client"
import { handleError } from "@/utils"
import useCustomToast from "./useCustomToast"

const isLoggedIn = () => {
  return localStorage.getItem("access_token") !== null
}

const useAuth = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const { data: user } = useQuery<UserPublic | null, Error>({
    queryKey: ["currentUser"],
    queryFn: async () =>
      (await UsersService.readUserMe({ throwOnError: true })).data,
    enabled: isLoggedIn(),
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
    const response = await LoginService.loginAccessToken({
      body: data,
      throwOnError: true,
    })
    localStorage.setItem("access_token", response.data.access_token)
  }

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: () => {
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
    navigate({ to: "/login" })
  }

  return {
    signUpMutation,
    loginMutation,
    logout,
    user,
  }
}

export { isLoggedIn }
export default useAuth
