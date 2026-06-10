import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export const useChatStore = create(
  persist(
    (set, get) => ({
      users: [],
      channels: [],
      groups: [],
      activeChatId: null,
      activeChannelId: null,
      activeGroupId: null,
      messages: [],
      unreadCounts: {},
      incomingRequests: [],
      contextMenuTarget: null,
      replyTo: null,
      groupSharedKeys: {},

      setUsers: (users) => set({ users }),
      addUser: (user) => set((state) => ({ users: [...state.users, user] })),
      updateUser: (id, data) => set((state) => ({
        users: state.users.map(u => u.id === id ? { ...u, ...data } : u),
      })),
      removeUser: (id) => set((state) => ({ users: state.users.filter(u => u.id !== id) })),

      setChannels: (channels) => set({ channels }),
      addChannel: (channel) => set((state) => ({ channels: [...state.channels, channel] })),
      updateChannel: (id, data) => set((state) => ({
        channels: state.channels.map(c => c.id === id ? { ...c, ...data } : c),
      })),
      removeChannel: (id) => set((state) => ({ channels: state.channels.filter(c => c.id !== id) })),

      setGroups: (groups) => set({ groups }),
      addGroup: (group) => set((state) => ({ groups: [...state.groups, group] })),
      updateGroup: (id, data) => set((state) => ({
        groups: state.groups.map(g => g.id === id ? { ...g, ...data } : g),
      })),
      removeGroup: (id) => set((state) => ({ groups: state.groups.filter(g => g.id !== id) })),

      setActiveChatId: (activeChatId) => set({ activeChatId }),
      setActiveChannelId: (activeChannelId) => set({ activeChannelId }),
      setActiveGroupId: (activeGroupId) => set({ activeGroupId }),

      setMessages: (messages) => set({ messages }),
      addMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),
      prependMessages: (messages) => set((state) => ({ messages: [...messages, ...state.messages] })),
      updateMessage: (id, data) => set((state) => ({
        messages: state.messages.map(m => m.id === id ? { ...m, ...data } : m),
      })),
      removeMessage: (id) => set((state) => ({ messages: state.messages.filter(m => m.id !== id) })),
      clearMessages: () => set({ messages: [] }),

      setUnreadCounts: (unreadCounts) => set({ unreadCounts }),
      incrementUnreadCount: (userId) => set((state) => ({
        unreadCounts: { ...state.unreadCounts, [userId]: (state.unreadCounts[userId] || 0) + 1 },
      })),
      resetUnreadCount: (userId) => set((state) => {
        const newCounts = { ...state.unreadCounts };
        delete newCounts[userId];
        return { unreadCounts: newCounts };
      }),

      setIncomingRequests: (incomingRequests) => set({ incomingRequests }),
      addIncomingRequest: (request) => set((state) => ({ incomingRequests: [...state.incomingRequests, request] })),
      removeIncomingRequest: (requesterId) => set((state) => ({
        incomingRequests: state.incomingRequests.filter(r => r.requester_id !== requesterId),
      })),

      setContextMenuTarget: (contextMenuTarget) => set({ contextMenuTarget }),
      setReplyTo: (replyTo) => set({ replyTo }),

      setGroupSharedKeys: (groupSharedKeys) => set({ groupSharedKeys }),
      setGroupSharedKey: (groupId, userId, key) => set((state) => ({
        groupSharedKeys: {
          ...state.groupSharedKeys,
          [groupId]: { ...(state.groupSharedKeys[groupId] || {}), [userId]: key },
        },
      })),
      removeGroupSharedKey: (groupId, userId) => set((state) => {
        const groupKeys = { ...state.groupSharedKeys[groupId] };
        delete groupKeys[userId];
        return {
          groupSharedKeys: {
            ...state.groupSharedKeys,
            [groupId]: groupKeys,
          },
        };
      }),

      reset: () => set({
        users: [],
        channels: [],
        groups: [],
        activeChatId: null,
        activeChannelId: null,
        activeGroupId: null,
        messages: [],
        unreadCounts: {},
        incomingRequests: [],
        contextMenuTarget: null,
        replyTo: null,
        groupSharedKeys: {},
      }),
    }),
    {
      name: 'securemsg-chat-store',
      partialize: (state) => ({
        users: state.users,
        channels: state.channels,
        groups: state.groups,
        groupSharedKeys: state.groupSharedKeys,
      }),
    }
  )
);

export const useAuthStore = create(
  persist(
    (set) => ({
      user: null,
      loading: true,
      setUser: (user) => set({ user, loading: false }),
      setLoading: (loading) => set({ loading }),
      logout: () => set({ user: null, loading: false }),
    }),
    {
      name: 'securemsg-auth-store',
    }
  )
);