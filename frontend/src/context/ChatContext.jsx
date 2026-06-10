import { createContext, useContext, useState } from "react";

const ChatContext = createContext(null);

export function useChat() {
  return useContext(ChatContext);
}

export function ChatProvider({ children }) {
  const [users, setUsers] = useState([]);
  const [channels, setChannels] = useState([]);
  const [groups, setGroups] = useState([]);
  const [activeChatId, setActiveChatId] = useState(null);
  const [activeChannelId, setActiveChannelId] = useState(null);
  const [activeGroupId, setActiveGroupId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [unreadCounts, setUnreadCounts] = useState({});
  const [incomingRequests, setIncomingRequests] = useState([]);
  const [contextMenuTarget, setContextMenuTarget] = useState(null);
  const [replyTo, setReplyTo] = useState(null);
  const [groupSharedKeys, setGroupSharedKeys] = useState({});

  function setGroupSharedKey(groupId, userId, key) {
    setGroupSharedKeys((prev) => ({
      ...prev,
      [groupId]: { ...(prev[groupId] || {}), [userId]: key },
    }));
  }

  const value = {
    users, setUsers,
    channels, setChannels,
    groups, setGroups,
    activeChatId, setActiveChatId,
    activeChannelId, setActiveChannelId,
    activeGroupId, setActiveGroupId,
    messages, setMessages,
    unreadCounts, setUnreadCounts,
    incomingRequests, setIncomingRequests,
    contextMenuTarget, setContextMenuTarget,
    replyTo, setReplyTo,
    groupSharedKeys, setGroupSharedKeys, setGroupSharedKey,
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}
