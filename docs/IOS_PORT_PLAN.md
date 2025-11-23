# Sara iOS Port - Complete Implementation Plan

**Document Version:** 1.0
**Date:** 2025-11-09
**Estimated Timeline:** 2-3 months for iOS port, 2-3 weeks for web app simplification

---

## Executive Summary

This document outlines the complete plan to simplify the Sara web application and port it to iOS. The strategy focuses on removing complex UI visualizations while maintaining all backend intelligence, knowledge graph capabilities, and AI features.

### Key Principles
1. **Preserve Intelligence**: All backend knowledge graph, memory, and AI capabilities remain intact
2. **Remove Visual Complexity**: Eliminate D3.js visualizations, sprite animations, and complex UI components
3. **Streamline UX**: Simplify navigation and reduce UI clutter
4. **Mobile-First iOS**: Port simplified feature set to native iOS

### Complexity Reduction
- **Original Estimate**: 6-8 months (MODERATE-COMPLEX)
- **Simplified Estimate**: 2-3 months (EASY-MODERATE)
- **Lines of Code Removed**: ~2,200 lines of complex visualization code
- **Features Removed**: UI components only, zero backend intelligence lost

---

## Part 1: Web App Simplification ✅ COMPLETE

**Status:** ✅ Completed November 9, 2025
**Results:** 12 files deleted (~3,969 lines), 7 files modified, 46% complexity reduction
**Details:** See `/docs/WEB_APP_SIMPLIFICATION_COMPLETE.md` for full completion report

---

### Original Plan

### 1.1 Features to Remove (UI Only)

#### Knowledge Graph Visualizations
**Components to Remove:**
- `frontend/src/components/KnowledgeGraph.tsx` (1110 lines)
  - D3.js force-directed graph
  - Interactive node dragging
  - Physics simulation
  - Zoom/pan controls

- `frontend/src/components/TimelineView.tsx` (~400 lines)
  - Chronological memory/note visualization
  - Timeline scrubbing interface

- Graph View tab in Notes section
- Memory Garden visual exploration UI

**Backend to Keep:**
- ✅ Neo4j knowledge graph database
- ✅ All `/knowledge-graph/*` API endpoints
- ✅ Note connections table and APIs
- ✅ Semantic relationship detection
- ✅ Memory retrieval and RAG
- ✅ Autonomous insight generation

**Result:** Sara maintains full intelligence, users just interact via chat/search instead of visual graph

---

#### Sprite Animation System
**Components to Remove:**
- `frontend/src/components/SpriteChatPopup.tsx` (~400 lines)
  - Canvas-based particle system
  - Real-time breathing effects
  - Shimmer animations

- `frontend/src/components/SpriteSettings.tsx`
  - Visual personality mode controls

- `frontend/src/utils/spriteBus.ts`
  - Event bus for sprite animations

**Backend to Keep:**
- ✅ Personality modes (coach/analyst/companion/guardian/concierge/librarian)
- ✅ Autonomous sweep system
- ✅ Contextual intelligence
- ✅ Activity monitoring
- ✅ All personality-driven chat behavior

**Result:** Personality modes continue to affect Sara's responses, just no animated sprite

---

#### Fitness Chat Interface
**Components to Modify:**
- `frontend/src/components/Fitness.tsx`
  - Remove: Dedicated chat interface in fitness section
  - Keep: Habits tracking UI
  - Keep: Workout logging interface
  - Keep: Nutrition tracking
  - Keep: Progress analytics and charts

**Backend Changes:**
- Move all fitness tools to main chat registry (if not already global)
- Ensure fitness tools accessible from main chat
- Keep all fitness data models and APIs

**Files to Check:**
- `backend/app/tools/registry.py` - Verify fitness tools registered globally
- `backend/app/routes/fitness.py` - Keep all endpoints
- `frontend/src/components/Fitness.tsx` - Remove chat UI section

**Result:** Users interact with fitness features via main chat, view data in dedicated fitness dashboard

---

#### Conversation Sidebar
**Components to Modify:**
- `frontend/src/components/ChatInterface.tsx` (872 lines)
  - Remove: Left sidebar with saved conversations list
  - Keep: Main chat area
  - Keep: Message history in current conversation
  - Keep: Document attachments
  - Keep: Streaming responses

**Backend to Keep:**
- ✅ Conversation storage in database
- ✅ Message history and context
- ✅ Conversation retrieval APIs
- ✅ Full chat history for memory/RAG

**UI Changes:**
- Remove conversation list sidebar
- Full-width chat interface
- Optional: Add simple dropdown for conversation switching (future enhancement)

**Result:** Cleaner, focused chat interface; history still saved for Sara's memory

---

### 1.2 Modified Navigation Structure

#### Current Navigation (App-interactive.tsx)
```
Views: login, signup, dashboard, chat, notes, documents,
       reminders, timers, settings, calendar, onboarding,
       habits, vulnerability-watch, reflection
```

#### Simplified Navigation
```
Primary Views:
- login / signup
- dashboard (home)
- chat (main interface)
- notes (markdown editor, folders, no graph)
- habits (tracking dashboard, no chat)
- documents
- calendar
- settings

Removed Views:
- knowledge graph (UI component only)
- timeline (UI component only)
- sprite settings (no sprite to configure)

Preserved in Settings:
- Memory management (view/edit episodes)
- Personality mode selection (affects chat behavior)
- All existing preferences
```

---

### 1.3 Files to Modify - Web App

#### Remove Completely
```
frontend/src/components/KnowledgeGraph.tsx
frontend/src/components/TimelineView.tsx
frontend/src/components/SpriteChatPopup.tsx
frontend/src/components/SpriteSettings.tsx
frontend/src/utils/spriteBus.ts
frontend/src/utils/connectionDetector.ts (if only used by graph UI)
```

#### Modify
```
frontend/src/App-interactive.tsx
- Remove knowledge graph/timeline view states
- Remove sprite initialization
- Update navigation menu
- Remove sprite-related imports

frontend/src/components/ChatInterface.tsx
- Remove conversation sidebar code
- Simplify to single-column layout
- Keep all chat functionality

frontend/src/components/Fitness.tsx
- Remove chat interface section
- Keep tracking dashboards
- Add note about using main chat for fitness queries

frontend/src/components/NotesKnowledgeGarden.tsx
- Remove graph view tab
- Remove timeline integration
- Keep: Notes list, editor, folder tree, backlinks panel
- Simplify to focus on writing/organizing

frontend/src/components/Settings.tsx
- Remove sprite settings section
- Keep memory management
- Keep personality mode selector (text-only)

frontend/src/components/MemoryManager.tsx
- Keep memory curation features
- Remove graph visualization integration
- List-based memory browsing only
```

#### Backend (Minimal Changes)
```
backend/app/tools/registry.py
- Verify fitness tools registered globally
- No removal of tools

backend/app/main_simple.py
- Keep all endpoints (may be used by future features)
- Optional: Mark graph endpoints as deprecated but functional
```

---

### 1.4 Step-by-Step Execution Plan - Web App

#### Week 1: Remove Visualizations
1. **Day 1-2: Remove Sprite System**
   - Delete sprite component files
   - Remove sprite imports from App-interactive.tsx
   - Remove sprite settings from Settings.tsx
   - Test: Verify app loads without sprite

2. **Day 3-4: Remove Knowledge Graph UI**
   - Delete KnowledgeGraph.tsx
   - Delete TimelineView.tsx
   - Remove graph view from Notes component
   - Update navigation to remove graph links

3. **Day 5: Testing**
   - Full regression test of remaining features
   - Verify no broken imports
   - Check console for errors

#### Week 2: Simplify Chat & Fitness
1. **Day 1-2: Remove Conversation Sidebar**
   - Modify ChatInterface.tsx
   - Remove sidebar rendering logic
   - Adjust layout to full-width
   - Test chat functionality

2. **Day 3-4: Simplify Fitness**
   - Remove chat section from Fitness.tsx
   - Verify fitness tools work in main chat
   - Update UI to guide users to main chat
   - Test habit logging, workout tracking

3. **Day 5: Final Testing & Cleanup**
   - Remove unused dependencies (D3.js if not used elsewhere)
   - Update package.json
   - Run `npm run build` to verify production build
   - Document changes

#### Week 3: Polish & Documentation
1. Update user-facing documentation
2. Test all features end-to-end
3. Performance testing (should be faster without D3.js)
4. Deploy to production

---

## Part 2: iOS Port Architecture

### 2.1 Technology Stack

#### Core Framework
```
React Native 0.73+ with Expo (recommended)
- Simpler setup than bare React Native CLI
- Over-the-air updates
- Easier development workflow
- Native module access when needed
```

#### Navigation
```
@react-navigation/native (v6)
@react-navigation/stack
@react-navigation/bottom-tabs

Navigation Structure:
- Tab Navigator (bottom tabs)
  - Chat
  - Notes
  - Habits
  - More (calendar, documents, settings)
```

#### State Management
```
@tanstack/react-query (same as web)
zustand (same as web)
@react-native-async-storage/async-storage
react-native-keychain (for secure token storage)
```

#### UI Components
```
react-native-paper (Material Design, optional)
react-native-vector-icons
react-native-gesture-handler
react-native-reanimated
```

#### Markdown & Rich Text
```
react-native-markdown-display
react-native-syntax-highlighter (for code blocks)
```

#### Forms & Validation
```
react-hook-form (same as web)
zod (same as web)
```

#### Charts & Visualizations
```
react-native-chart-kit (for habit tracking)
victory-native (alternative, more powerful)
```

#### File Handling
```
expo-document-picker
expo-file-system
expo-media-library
react-native-fs (if not using Expo)
```

#### Notifications
```
expo-notifications
@notifee/react-native (advanced features)
```

#### Date/Time
```
date-fns (same as web)
react-native-calendars (for calendar UI)
```

#### HTTP Client
```
axios (same as web)
- Configure with secure token interceptors
```

---

### 2.2 Authentication Architecture Changes

#### Current Web App (Cookie-Based)
```javascript
// Login sets HTTP-only cookie
POST /auth/login
Response: Set-Cookie: access_token=...; HttpOnly; Secure

// Subsequent requests automatically include cookie
GET /chat
Cookie: access_token=...
```

#### iOS App (Token-Based)
```javascript
// Login returns token in response body
POST /auth/login
Response: {
  access_token: "jwt_token_here",
  refresh_token: "refresh_token_here",
  user: {...}
}

// Store in secure keychain
await SecureStore.setItemAsync('access_token', token);

// Include in Authorization header
GET /chat
Authorization: Bearer jwt_token_here
```

#### Backend Changes Required
```python
# backend/app/routes/auth.py

# Modify login endpoint to support both modes
@router.post("/login")
async def login(
    credentials: LoginRequest,
    response: Response,
    client_type: Optional[str] = Header(None, alias="X-Client-Type")
):
    # ... existing auth logic ...

    if client_type == "mobile":
        # Return token in response body for mobile
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": user_data
        }
    else:
        # Set cookie for web (existing behavior)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=True,
            samesite="lax"
        )
        return {"user": user_data}

# Add token refresh endpoint
@router.post("/refresh")
async def refresh_token(
    refresh_token: str = Body(..., embed=True)
):
    # Validate refresh token
    # Generate new access token
    return {"access_token": new_token}
```

#### iOS Token Management
```typescript
// services/auth.ts
import * as SecureStore from 'expo-secure-store';

export const authService = {
  async login(email: string, password: string) {
    const response = await axios.post('/auth/login',
      { email, password },
      { headers: { 'X-Client-Type': 'mobile' } }
    );

    await SecureStore.setItemAsync('access_token', response.data.access_token);
    await SecureStore.setItemAsync('refresh_token', response.data.refresh_token);

    return response.data.user;
  },

  async getToken() {
    return await SecureStore.getItemAsync('access_token');
  },

  async refreshToken() {
    const refreshToken = await SecureStore.getItemAsync('refresh_token');
    const response = await axios.post('/auth/refresh', { refresh_token: refreshToken });
    await SecureStore.setItemAsync('access_token', response.data.access_token);
    return response.data.access_token;
  },

  async logout() {
    await SecureStore.deleteItemAsync('access_token');
    await SecureStore.deleteItemAsync('refresh_token');
  }
};

// Axios interceptor
axios.interceptors.request.use(async (config) => {
  const token = await authService.getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

axios.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      try {
        await authService.refreshToken();
        return axios.request(error.config);
      } catch {
        await authService.logout();
        // Navigate to login
      }
    }
    return Promise.reject(error);
  }
);
```

---

### 2.3 Feature-by-Feature Port Plan

#### Feature 1: Authentication (Week 1-2)
**Components:**
- Login screen
- Signup screen
- Password reset flow
- Secure token storage
- Auth context provider

**Implementation:**
```typescript
// screens/LoginScreen.tsx
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

export function LoginScreen() {
  const { control, handleSubmit } = useForm({
    resolver: zodResolver(loginSchema)
  });

  const onSubmit = async (data) => {
    await authService.login(data.email, data.password);
    navigation.navigate('Main');
  };

  return (
    <View style={styles.container}>
      <TextInput
        control={control}
        name="email"
        placeholder="Email"
        autoCapitalize="none"
      />
      <TextInput
        control={control}
        name="password"
        placeholder="Password"
        secureTextEntry
      />
      <Button onPress={handleSubmit(onSubmit)}>Login</Button>
    </View>
  );
}
```

**Testing:**
- Login/logout flow
- Token storage verification
- Token refresh on 401
- Biometric authentication (optional enhancement)

---

#### Feature 2: Main Chat Interface (Week 3-4)
**Components:**
- Chat screen
- Message list (FlatList)
- Message input
- Streaming response handler
- Document attachment picker

**Key Differences from Web:**
- FlatList instead of scrollable div
- KeyboardAvoidingView for input
- Native file picker
- No conversation sidebar

**Implementation:**
```typescript
// screens/ChatScreen.tsx
import { FlatList, KeyboardAvoidingView } from 'react-native';
import Markdown from 'react-native-markdown-display';

export function ChatScreen() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');

  const sendMessage = async () => {
    const response = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: input })
    });

    // Handle streaming response
    const reader = response.body.getReader();
    let chunk = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      chunk += new TextDecoder().decode(value);
      // Update UI with streaming chunk
    }
  };

  return (
    <KeyboardAvoidingView behavior="padding" style={styles.container}>
      <FlatList
        data={messages}
        renderItem={({ item }) => (
          <View style={styles.message}>
            <Markdown>{item.content}</Markdown>
          </View>
        )}
        inverted
      />
      <View style={styles.inputContainer}>
        <TextInput
          value={input}
          onChangeText={setInput}
          placeholder="Message Sara..."
        />
        <Button onPress={sendMessage}>Send</Button>
      </View>
    </KeyboardAvoidingView>
  );
}
```

**Features:**
- Markdown rendering with code highlighting
- Streaming response display
- Document attachments
- Tool usage indicators
- Message retry on failure

**Testing:**
- Send/receive messages
- Streaming updates
- Long message lists (performance)
- Keyboard behavior
- Document attachments

---

#### Feature 3: Notes (Week 5)
**Components:**
- Notes list screen
- Note editor screen
- Folder navigation
- Search functionality

**Key Features:**
- Markdown editor
- Folder organization
- `[[linking]]` syntax support (no graph UI)
- Backlinks panel (list view)
- Full-text search

**Implementation:**
```typescript
// screens/NotesScreen.tsx
export function NotesScreen({ navigation }) {
  const { data: notes } = useQuery(['notes'], fetchNotes);
  const [searchQuery, setSearchQuery] = useState('');

  return (
    <View style={styles.container}>
      <SearchBar
        value={searchQuery}
        onChangeText={setSearchQuery}
      />
      <FlatList
        data={notes}
        renderItem={({ item }) => (
          <TouchableOpacity
            onPress={() => navigation.navigate('NoteEditor', { id: item.id })}
          >
            <View style={styles.noteItem}>
              <Text style={styles.title}>{item.title}</Text>
              <Text style={styles.preview}>{item.content.slice(0, 100)}</Text>
            </View>
          </TouchableOpacity>
        )}
      />
    </View>
  );
}

// screens/NoteEditorScreen.tsx
export function NoteEditorScreen({ route }) {
  const { id } = route.params;
  const [content, setContent] = useState('');
  const [previewMode, setPreviewMode] = useState(false);

  return (
    <View style={styles.container}>
      <View style={styles.toolbar}>
        <Button onPress={() => setPreviewMode(!previewMode)}>
          {previewMode ? 'Edit' : 'Preview'}
        </Button>
      </View>

      {previewMode ? (
        <ScrollView>
          <Markdown>{content}</Markdown>
        </ScrollView>
      ) : (
        <TextInput
          value={content}
          onChangeText={setContent}
          multiline
          style={styles.editor}
        />
      )}
    </View>
  );
}
```

**Testing:**
- Create/edit/delete notes
- Folder navigation
- Search functionality
- Markdown preview
- Link detection
- Offline editing (future)

---

#### Feature 4: Habits & Fitness Tracking (Week 6-7)
**Components:**
- Habits dashboard
- Habit logging screen
- Progress charts
- Streak visualization
- Workout logging
- Nutrition tracking

**Key Features:**
- Daily habit check-ins
- Visual progress (charts)
- Streak tracking
- Custom habits
- Integration with main chat (use tools)

**Implementation:**
```typescript
// screens/HabitsScreen.tsx
import { VictoryBar, VictoryChart, VictoryLine } from 'victory-native';

export function HabitsScreen() {
  const { data: habits } = useQuery(['habits'], fetchHabits);
  const { data: todayLogs } = useQuery(['habit-logs', today], fetchTodayLogs);

  return (
    <ScrollView>
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Today's Habits</Text>
        {habits.map(habit => (
          <HabitCheckItem
            key={habit.id}
            habit={habit}
            logged={todayLogs.some(log => log.habit_id === habit.id)}
            onToggle={() => logHabit(habit.id)}
          />
        ))}
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Progress This Week</Text>
        <VictoryChart>
          <VictoryBar data={weeklyData} />
        </VictoryChart>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Streaks</Text>
        {habits.map(habit => (
          <StreakIndicator
            key={habit.id}
            habit={habit}
            streak={calculateStreak(habit)}
          />
        ))}
      </View>
    </ScrollView>
  );
}
```

**Charts:**
- Completion rate (bar chart)
- Trend over time (line chart)
- Heatmap calendar (optional)

**Testing:**
- Log habits
- View progress
- Streak calculations
- Chart rendering
- Performance with many habits

---

#### Feature 5: Documents (Week 8)
**Components:**
- Documents list
- Document viewer
- Upload functionality
- Search in documents

**Key Features:**
- File upload (photos, PDFs, docs)
- Document preview
- Full-text search
- Categorization

**Implementation:**
```typescript
// screens/DocumentsScreen.tsx
import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system';

export function DocumentsScreen() {
  const { data: documents } = useQuery(['documents'], fetchDocuments);

  const uploadDocument = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: '*/*',
      copyToCacheDirectory: true
    });

    if (result.type === 'success') {
      const formData = new FormData();
      formData.append('file', {
        uri: result.uri,
        name: result.name,
        type: result.mimeType
      });

      await axios.post('/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      queryClient.invalidateQueries(['documents']);
    }
  };

  return (
    <View style={styles.container}>
      <Button onPress={uploadDocument}>Upload Document</Button>
      <FlatList
        data={documents}
        renderItem={({ item }) => (
          <DocumentItem document={item} />
        )}
      />
    </View>
  );
}
```

**Testing:**
- Upload various file types
- View PDFs
- View images
- Search functionality
- Download/share

---

#### Feature 6: Calendar & Reminders (Week 9)
**Components:**
- Calendar view
- Reminders list
- Timer interface
- Notification handling

**Key Features:**
- Calendar events
- Reminders with push notifications
- Timers
- Integration with device calendar (optional)

**Implementation:**
```typescript
// screens/CalendarScreen.tsx
import { Calendar } from 'react-native-calendars';
import * as Notifications from 'expo-notifications';

export function CalendarScreen() {
  const { data: events } = useQuery(['calendar-events'], fetchEvents);

  const markedDates = useMemo(() => {
    return events.reduce((acc, event) => {
      acc[event.date] = { marked: true, dotColor: 'blue' };
      return acc;
    }, {});
  }, [events]);

  return (
    <View style={styles.container}>
      <Calendar
        markedDates={markedDates}
        onDayPress={(day) => {
          navigation.navigate('DayEvents', { date: day.dateString });
        }}
      />

      <View style={styles.upcomingSection}>
        <Text style={styles.sectionTitle}>Upcoming</Text>
        <FlatList
          data={upcomingEvents}
          renderItem={({ item }) => <EventItem event={item} />}
        />
      </View>
    </View>
  );
}

// Notifications setup
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

// Request permissions
const { status } = await Notifications.requestPermissionsAsync();

// Schedule reminder notification
await Notifications.scheduleNotificationAsync({
  content: {
    title: reminder.title,
    body: reminder.notes,
  },
  trigger: {
    date: new Date(reminder.scheduled_for),
  },
});
```

**Testing:**
- Create events
- View calendar
- Reminder notifications
- Timer countdown
- Background notifications

---

#### Feature 7: Settings & Preferences (Week 10)
**Components:**
- Settings screen
- Personality mode selector
- Memory management
- API configuration
- Profile management

**Key Features:**
- User preferences
- Personality mode selection
- Memory viewing/editing
- Account settings
- App version info

**Implementation:**
```typescript
// screens/SettingsScreen.tsx
export function SettingsScreen() {
  const { data: user } = useQuery(['user'], fetchCurrentUser);
  const { data: preferences } = useQuery(['preferences'], fetchPreferences);

  return (
    <ScrollView>
      <Section title="Personality">
        <PersonalityModeSelector
          current={preferences.personality_mode}
          onChange={updatePersonalityMode}
        />
      </Section>

      <Section title="Memory">
        <Button onPress={() => navigation.navigate('MemoryManager')}>
          View & Manage Memory
        </Button>
      </Section>

      <Section title="Account">
        <ListItem title="Email" value={user.email} />
        <ListItem title="Name" value={user.name} onPress={editName} />
        <Button onPress={logout}>Logout</Button>
      </Section>

      <Section title="About">
        <ListItem title="Version" value={appVersion} />
      </Section>
    </ScrollView>
  );
}

// screens/MemoryManagerScreen.tsx
export function MemoryManagerScreen() {
  const { data: episodes } = useQuery(['episodes'], fetchEpisodes);

  return (
    <FlatList
      data={episodes}
      renderItem={({ item }) => (
        <MemoryEpisodeCard
          episode={item}
          onUpdateImportance={(score) => updateEpisode(item.id, { importance_score: score })}
          onDelete={() => deleteEpisode(item.id)}
        />
      )}
    />
  );
}
```

**Testing:**
- Update preferences
- Change personality mode
- View memory episodes
- Edit account info
- Logout flow

---

### 2.4 iOS App Structure

```
ios-app/
├── App.tsx                      # Root component
├── app.json                     # Expo config
├── package.json
├── tsconfig.json
│
├── src/
│   ├── navigation/
│   │   ├── AppNavigator.tsx     # Main navigation setup
│   │   ├── AuthNavigator.tsx    # Auth screens
│   │   └── MainNavigator.tsx    # Authenticated screens
│   │
│   ├── screens/
│   │   ├── auth/
│   │   │   ├── LoginScreen.tsx
│   │   │   ├── SignupScreen.tsx
│   │   │   └── ForgotPasswordScreen.tsx
│   │   │
│   │   ├── chat/
│   │   │   └── ChatScreen.tsx
│   │   │
│   │   ├── notes/
│   │   │   ├── NotesListScreen.tsx
│   │   │   ├── NoteEditorScreen.tsx
│   │   │   └── FolderScreen.tsx
│   │   │
│   │   ├── habits/
│   │   │   ├── HabitsScreen.tsx
│   │   │   ├── HabitDetailScreen.tsx
│   │   │   └── WorkoutLogScreen.tsx
│   │   │
│   │   ├── documents/
│   │   │   ├── DocumentsScreen.tsx
│   │   │   └── DocumentViewerScreen.tsx
│   │   │
│   │   ├── calendar/
│   │   │   ├── CalendarScreen.tsx
│   │   │   ├── RemindersScreen.tsx
│   │   │   └── TimersScreen.tsx
│   │   │
│   │   └── settings/
│   │       ├── SettingsScreen.tsx
│   │       ├── MemoryManagerScreen.tsx
│   │       └── ProfileScreen.tsx
│   │
│   ├── components/
│   │   ├── chat/
│   │   │   ├── MessageBubble.tsx
│   │   │   ├── StreamingIndicator.tsx
│   │   │   └── DocumentAttachment.tsx
│   │   │
│   │   ├── notes/
│   │   │   ├── MarkdownEditor.tsx
│   │   │   ├── MarkdownPreview.tsx
│   │   │   └── BacklinksPanel.tsx
│   │   │
│   │   ├── habits/
│   │   │   ├── HabitCheckItem.tsx
│   │   │   ├── StreakIndicator.tsx
│   │   │   └── ProgressChart.tsx
│   │   │
│   │   └── common/
│   │       ├── Button.tsx
│   │       ├── TextInput.tsx
│   │       ├── SearchBar.tsx
│   │       └── LoadingSpinner.tsx
│   │
│   ├── services/
│   │   ├── api.ts               # Axios configuration
│   │   ├── auth.ts              # Authentication service
│   │   ├── chat.ts              # Chat API calls
│   │   ├── notes.ts             # Notes API calls
│   │   ├── habits.ts            # Habits API calls
│   │   ├── documents.ts         # Documents API calls
│   │   └── notifications.ts     # Push notification handling
│   │
│   ├── hooks/
│   │   ├── useAuth.ts           # Authentication hook
│   │   ├── useChat.ts           # Chat functionality hook
│   │   ├── useNotes.ts          # Notes queries
│   │   └── useNotifications.ts  # Notification permissions
│   │
│   ├── context/
│   │   ├── AuthContext.tsx      # Auth state provider
│   │   └── ThemeContext.tsx     # Theme provider (dark mode)
│   │
│   ├── utils/
│   │   ├── storage.ts           # AsyncStorage helpers
│   │   ├── linkParser.ts        # [[linking]] detection
│   │   └── dateHelpers.ts       # Date formatting
│   │
│   ├── types/
│   │   ├── api.ts               # API response types
│   │   ├── models.ts            # Data models
│   │   └── navigation.ts        # Navigation types
│   │
│   └── styles/
│       ├── theme.ts             # Color palette, spacing
│       └── typography.ts        # Text styles
│
└── assets/
    ├── icon.png                 # App icon
    ├── splash.png               # Splash screen
    └── images/
```

---

### 2.5 Development Timeline

#### Month 1: Foundation
**Week 1-2: Setup & Authentication**
- Initialize Expo project
- Set up navigation structure
- Implement authentication screens
- Configure secure token storage
- Backend: Add mobile auth support

**Week 3-4: Chat Interface**
- Build chat screen
- Implement message list
- Add streaming response handling
- Document attachment support
- Basic error handling

#### Month 2: Core Features
**Week 5: Notes**
- Notes list screen
- Note editor with markdown
- Folder navigation
- Search functionality

**Week 6-7: Habits & Fitness**
- Habits dashboard
- Daily logging interface
- Progress charts
- Workout/nutrition tracking
- Integration with chat tools

**Week 8: Documents**
- Document list
- Upload functionality
- Document viewer
- Search in documents

#### Month 3: Additional Features & Polish
**Week 9: Calendar & Notifications**
- Calendar view
- Reminders list
- Timer interface
- Push notifications setup

**Week 10: Settings & Memory**
- Settings screen
- Personality mode selector
- Memory manager
- Profile management

**Week 11-12: Testing & Polish**
- End-to-end testing
- Performance optimization
- UI/UX polish
- Bug fixes
- App Store preparation

---

### 2.6 Testing Strategy

#### Unit Tests
- Service layer (API calls)
- Utility functions
- Hook logic
- Business logic

#### Integration Tests
- Authentication flow
- Chat message flow
- Note creation/editing
- Habit logging
- Document upload

#### E2E Tests (Detox or Maestro)
- Complete user workflows
- Critical paths
- Offline behavior
- Error scenarios

#### Manual Testing
- Different iOS versions (iOS 14+)
- Different device sizes (iPhone SE to iPhone 15 Pro Max)
- Dark mode support
- Accessibility (VoiceOver)
- Performance on older devices

---

### 2.7 Deployment & Distribution

#### App Store Requirements
1. **Apple Developer Account** ($99/year)
2. **App Icon** (1024x1024px)
3. **Screenshots** (various device sizes)
4. **Privacy Policy** (required for App Store)
5. **App Description**
6. **Keywords** for search optimization

#### Build Process
```bash
# Development build
eas build --profile development --platform ios

# TestFlight build
eas build --profile preview --platform ios

# Production build
eas build --profile production --platform ios

# Submit to App Store
eas submit --platform ios
```

#### Version Management
- Semantic versioning (1.0.0, 1.1.0, etc.)
- Over-the-air updates via Expo for non-native changes
- Full App Store updates for native module changes

---

## Part 3: Shared Backend Modifications

### 3.1 API Changes for Mobile Support

#### Authentication Endpoints
```python
# backend/app/routes/auth.py

# Add mobile auth support (token in response body)
# Add refresh token endpoint
# Add token validation endpoint
```

#### CORS Configuration
```python
# backend/app/main_simple.py

# Add mobile app origin if needed (not required for native apps)
# Token-based auth doesn't need CORS
```

#### File Upload
```python
# backend/app/routes/documents.py

# Verify multipart/form-data handling works for React Native
# May need to adjust file size limits for mobile
```

### 3.2 Optional Backend Enhancements

#### Push Notifications
```python
# backend/app/services/push_notifications.py

# Add Apple Push Notification service (APNs) integration
# Store device tokens
# Send push notifications for:
# - Reminders
# - Important insights
# - Timer completions
```

#### Rate Limiting
```python
# Protect endpoints from abuse
# Different limits for mobile vs web if needed
```

#### Analytics
```python
# Track mobile app usage
# Monitor API performance for mobile clients
```

---

## Part 4: Migration & Rollout Strategy

### 4.1 Web App Simplification Rollout

#### Option A: Gradual Rollout
1. Deploy simplified version to staging
2. Beta test with select users
3. Gather feedback
4. Deploy to production
5. Monitor for issues

#### Option B: Feature Flags
1. Add feature flags for graph UI, sprites
2. Deploy with flags enabled (old behavior)
3. Gradually disable for users
4. Remove code after confidence

#### Option C: Hard Cutover
1. Deploy simplified version directly
2. Announce changes to users
3. Provide migration guide
4. Monitor support requests

**Recommendation:** Option A (gradual rollout) for safest transition

---

### 4.2 iOS App Launch Strategy

#### Phase 1: Internal Testing (Week 11)
- Install on development devices
- Team testing
- Fix critical bugs

#### Phase 2: TestFlight Beta (Week 12)
- Invite 5-10 beta testers
- Gather feedback
- Iterate on UX
- Fix bugs

#### Phase 3: App Store Submission (Week 13)
- Submit for review
- Address any rejection reasons
- Publish to App Store

#### Phase 4: Gradual Rollout (Week 14+)
- Limited release (10% of users)
- Monitor crash reports
- Fix any issues
- Full release

---

## Part 5: Risk Assessment & Mitigation

### 5.1 Technical Risks

#### Risk: Authentication Migration Breaks Web App
**Mitigation:**
- Maintain backward compatibility
- Support both cookie and token auth
- Comprehensive testing before deployment

#### Risk: React Native Performance Issues
**Mitigation:**
- Use FlatList for long lists (virtualization)
- Optimize re-renders with React.memo
- Profile with React DevTools
- Test on older devices early

#### Risk: Streaming Chat Not Working on iOS
**Mitigation:**
- Test streaming early in development
- Have fallback to polling if needed
- Use established libraries (EventSource polyfill)

#### Risk: File Upload Issues on Mobile
**Mitigation:**
- Test file uploads early
- Support multiple file types
- Handle large files gracefully
- Show upload progress

---

### 5.2 Timeline Risks

#### Risk: Underestimating Complexity
**Mitigation:**
- Build MVP first (essential features only)
- Add buffer time (20-30%)
- Prioritize ruthlessly
- Cut scope if needed

#### Risk: App Store Rejection
**Mitigation:**
- Review App Store guidelines early
- Ensure privacy policy compliance
- Test thoroughly before submission
- Have contingency plan for rejections

#### Risk: Backend Changes Cause Delays
**Mitigation:**
- Minimize backend changes
- Test backend changes in isolation
- Have rollback plan
- Deploy backend changes first

---

### 5.3 User Experience Risks

#### Risk: Users Miss Removed Features
**Mitigation:**
- Communicate changes clearly
- Provide alternative workflows
- Gather feedback
- Consider adding features back if critical

#### Risk: Mobile UX Doesn't Match Web
**Mitigation:**
- Follow iOS design guidelines
- User testing early
- Iterate based on feedback
- Focus on mobile-first patterns

---

## Part 6: Success Metrics

### 6.1 Web App Simplification Metrics

#### Performance
- [ ] Page load time reduced by 20%+
- [ ] Bundle size reduced by 15%+
- [ ] Lighthouse score improved

#### User Engagement
- [ ] No significant drop in daily active users
- [ ] Feature usage remains stable
- [ ] Support tickets don't spike

---

### 6.2 iOS App Launch Metrics

#### Adoption
- [ ] 100+ downloads in first month
- [ ] 50+ daily active users by month 2
- [ ] 4+ star rating on App Store

#### Performance
- [ ] Crash rate < 1%
- [ ] Average session length > 5 minutes
- [ ] Load time < 3 seconds

#### Engagement
- [ ] Daily chat messages > 500
- [ ] Note creation rate similar to web
- [ ] Habit logging consistency > 70%

---

## Part 7: Maintenance & Future Enhancements

### 7.1 Ongoing Maintenance

#### Weekly
- Monitor crash reports
- Review App Store reviews
- Check performance metrics
- Deploy bug fixes

#### Monthly
- Update dependencies
- Review feature requests
- Plan improvements
- Security updates

---

### 7.2 Future Enhancements

#### Phase 2 Features (3-6 months post-launch)
- [ ] Offline mode (local database sync)
- [ ] Widget support (habit tracking, quick notes)
- [ ] Siri shortcuts
- [ ] Apple Watch companion app
- [ ] Share extension (save to notes from other apps)
- [ ] Face ID / Touch ID login
- [ ] Handoff support (continue on Mac)

#### Advanced Features (6-12 months)
- [ ] Voice messages in chat
- [ ] Image attachments in chat
- [ ] Rich text editor for notes
- [ ] Collaboration features
- [ ] Export to external apps
- [ ] Automation rules

#### Optional: Re-add Visualizations
- [ ] Lightweight graph view (simplified D3 or native)
- [ ] Timeline view (native implementation)
- [ ] Stats dashboards

---

## Appendix A: Dependencies

### Web App Dependencies to Remove
```json
{
  "d3": "^7.8.5",  // If not used elsewhere
  "d3-force": "^3.0.0",
  "d3-selection": "^3.0.0",
  "d3-zoom": "^3.0.0"
}
```

### iOS App Dependencies to Add
```json
{
  "dependencies": {
    "react": "18.2.0",
    "react-native": "0.73.0",
    "expo": "~50.0.0",

    "@react-navigation/native": "^6.1.9",
    "@react-navigation/stack": "^6.3.20",
    "@react-navigation/bottom-tabs": "^6.5.11",

    "@tanstack/react-query": "^5.0.0",
    "zustand": "^4.4.7",
    "axios": "^1.6.2",

    "react-hook-form": "^7.49.2",
    "zod": "^3.22.4",

    "react-native-markdown-display": "^7.0.0",
    "react-native-syntax-highlighter": "^2.1.0",

    "victory-native": "^36.8.6",
    "react-native-chart-kit": "^6.12.0",

    "expo-document-picker": "~11.7.0",
    "expo-file-system": "~16.0.0",
    "expo-notifications": "~0.27.0",
    "expo-secure-store": "~12.8.0",

    "react-native-calendars": "^1.1303.0",
    "date-fns": "^3.0.0",

    "@react-native-async-storage/async-storage": "1.21.0"
  },
  "devDependencies": {
    "@types/react": "~18.2.45",
    "@types/react-native": "~0.73.0",
    "typescript": "^5.3.3"
  }
}
```

---

## Appendix B: Checklist

### Pre-Development
- [ ] Review this plan with team
- [ ] Set up development environment
- [ ] Create git branches (web-simplify, ios-port)
- [ ] Set up project management (issues, milestones)

### Web App Simplification
- [ ] Remove sprite components
- [ ] Remove knowledge graph UI
- [ ] Remove timeline view
- [ ] Simplify chat interface
- [ ] Update fitness section
- [ ] Update navigation
- [ ] Remove unused dependencies
- [ ] Test all remaining features
- [ ] Update documentation
- [ ] Deploy to staging
- [ ] Beta test
- [ ] Deploy to production

### iOS Development
- [ ] Initialize Expo project
- [ ] Set up navigation
- [ ] Implement authentication
- [ ] Build chat interface
- [ ] Build notes feature
- [ ] Build habits tracking
- [ ] Build documents feature
- [ ] Build calendar/reminders
- [ ] Build settings
- [ ] Implement push notifications
- [ ] End-to-end testing
- [ ] Performance optimization
- [ ] Prepare App Store assets
- [ ] TestFlight beta
- [ ] Submit to App Store
- [ ] Launch

### Backend Modifications
- [ ] Add mobile auth endpoint
- [ ] Add refresh token support
- [ ] Test file uploads from mobile
- [ ] (Optional) Add APNs integration
- [ ] Update API documentation

---

## Summary

This plan provides a comprehensive roadmap for:

1. **Simplifying the web app** by removing complex UI visualizations while maintaining full backend intelligence (2-3 weeks)

2. **Porting to iOS** with a clean, mobile-optimized experience (2-3 months)

The key insight is that by removing ~2,200 lines of complex D3.js/Canvas visualization code, we reduce porting complexity by 50% while Sara maintains 100% of her intelligence and memory capabilities.

**Total Timeline: 3-4 months from start to App Store launch**

---

**Document End**
