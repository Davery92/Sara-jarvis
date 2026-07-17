import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
  TextInput,
  Modal,
  Alert,
} from 'react-native';
import { colors, fontSizes } from '../../styles/theme';
import apiClient from '../../services/api';
import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system';
import * as Linking from 'expo-linking';
import type {
  Project,
  Task,
  TaskBoard,
  QAChecklistItem,
  QAPendingTask,
  QAPendingCommit,
  ProjectFolder,
  ProjectFile,
  FileListResponse,
} from '../../types/api';

type ViewMode = 'board' | 'qa' | 'files';

export default function ProjectsScreen() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('board');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [showCreateTask, setShowCreateTask] = useState(false);

  // Create Task form state
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskDescription, setNewTaskDescription] = useState('');
  const [newTaskType, setNewTaskType] = useState<'feature' | 'bug' | 'task' | 'chore'>('task');
  const [newTaskPriority, setNewTaskPriority] = useState<'low' | 'medium' | 'high' | 'critical' | null>(null);
  const [creatingTask, setCreatingTask] = useState(false);

  // Task Board state
  const [board, setBoard] = useState<TaskBoard | null>(null);
  const [boardLoading, setBoardLoading] = useState(false);

  // QA state
  const [checklist, setChecklist] = useState<QAChecklistItem[]>([]);
  const [pendingTasks, setPendingTasks] = useState<QAPendingTask[]>([]);
  const [qaLoading, setQaLoading] = useState(false);
  const [checkedItems, setCheckedItems] = useState<Record<string, string[]>>({});
  const [qaNote, setQaNote] = useState<Record<string, string>>({});

  // Files state
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [folders, setFolders] = useState<ProjectFolder[]>([]);
  const [breadcrumb, setBreadcrumb] = useState<ProjectFolder[]>([]);
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [filesLoading, setFilesLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [showCreateFolder, setShowCreateFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    if (selectedProject) {
      if (viewMode === 'board') {
        loadBoard();
      } else if (viewMode === 'qa') {
        loadQAData();
      } else if (viewMode === 'files') {
        loadFiles(null);
      }
    }
  }, [selectedProject, viewMode]);

  const loadProjects = async () => {
    try {
      setLoading(true);
      const response = await apiClient.get<{ projects: Project[] }>('/api/projects');
      setProjects(response.projects || []);
      if (response.projects?.length > 0 && !selectedProject) {
        setSelectedProject(response.projects[0]);
      }
    } catch (error) {
      console.error('Failed to load projects:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadBoard = async () => {
    if (!selectedProject) return;
    try {
      setBoardLoading(true);
      const response = await apiClient.get<TaskBoard>(
        `/api/projects/${selectedProject.id}/board`
      );
      setBoard(response);
    } catch (error) {
      console.error('Failed to load board:', error);
    } finally {
      setBoardLoading(false);
    }
  };

  const loadQAData = async () => {
    if (!selectedProject) return;
    try {
      setQaLoading(true);
      const [checklistRes, pendingRes] = await Promise.all([
        apiClient.get<{ items: QAChecklistItem[] }>(
          `/api/projects/${selectedProject.id}/qa/checklist`
        ),
        apiClient.get<{ tasks: QAPendingTask[] }>(
          `/api/projects/${selectedProject.id}/qa/pending`
        ),
      ]);
      setChecklist(checklistRes.items || []);
      setPendingTasks(pendingRes.tasks || []);
    } catch (error) {
      console.error('Failed to load QA data:', error);
    } finally {
      setQaLoading(false);
    }
  };

  const loadFiles = async (folderId: string | null) => {
    if (!selectedProject) return;
    try {
      setFilesLoading(true);
      const url = folderId
        ? `/api/projects/${selectedProject.id}/files?folder_id=${folderId}`
        : `/api/projects/${selectedProject.id}/files`;

      const response = await apiClient.get<FileListResponse>(url);
      setFiles(response.files || []);
      setFolders(response.folders || []);
      setBreadcrumb(response.breadcrumb || []);
      setCurrentFolderId(response.current_folder_id);
    } catch (error) {
      console.error('Failed to load files:', error);
    } finally {
      setFilesLoading(false);
    }
  };

  const handleUploadFile = async () => {
    if (!selectedProject) return;

    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: '*/*',
        copyToCacheDirectory: true,
      });

      if (result.canceled) return;

      const file = result.assets[0];
      setUploading(true);

      // Create form data
      const formData = new FormData();
      formData.append('file', {
        uri: file.uri,
        name: file.name,
        type: file.mimeType || 'application/octet-stream',
      } as any);

      if (currentFolderId) {
        formData.append('folder_id', currentFolderId);
      }

      await apiClient.upload(
        `/api/projects/${selectedProject.id}/files/upload`,
        formData
      );

      loadFiles(currentFolderId);
      Alert.alert('Success', 'File uploaded successfully');
    } catch (error) {
      console.error('Failed to upload file:', error);
      Alert.alert('Error', 'Failed to upload file');
    } finally {
      setUploading(false);
    }
  };

  const handleCreateFolder = async () => {
    if (!selectedProject || !newFolderName.trim()) return;

    try {
      await apiClient.post(`/api/projects/${selectedProject.id}/files/folders`, {
        name: newFolderName.trim(),
        parent_id: currentFolderId,
      });

      setNewFolderName('');
      setShowCreateFolder(false);
      loadFiles(currentFolderId);
    } catch (error) {
      console.error('Failed to create folder:', error);
      Alert.alert('Error', 'Failed to create folder');
    }
  };

  const handleDeleteFile = async (fileId: string) => {
    if (!selectedProject) return;

    Alert.alert(
      'Delete File',
      'Are you sure you want to delete this file?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await apiClient.delete(`/api/projects/${selectedProject.id}/files/${fileId}`);
              loadFiles(currentFolderId);
            } catch (error) {
              console.error('Failed to delete file:', error);
              Alert.alert('Error', 'Failed to delete file');
            }
          },
        },
      ]
    );
  };

  const handleDeleteFolder = async (folderId: string) => {
    if (!selectedProject) return;

    Alert.alert(
      'Delete Folder',
      'Are you sure you want to delete this folder and all its contents?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await apiClient.delete(`/api/projects/${selectedProject.id}/files/folders/${folderId}`);
              loadFiles(currentFolderId);
            } catch (error) {
              console.error('Failed to delete folder:', error);
              Alert.alert('Error', 'Failed to delete folder');
            }
          },
        },
      ]
    );
  };

  const handleDownloadFile = async (file: ProjectFile) => {
    if (!selectedProject) return;

    try {
      const downloadUrl = `${apiClient.getBaseUrl()}/api/projects/${selectedProject.id}/files/${file.id}/download`;
      await Linking.openURL(downloadUrl);
    } catch (error) {
      console.error('Failed to download file:', error);
      Alert.alert('Error', 'Failed to download file');
    }
  };

  const navigateToFolder = (folderId: string | null) => {
    loadFiles(folderId);
  };

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await loadProjects();
    if (selectedProject) {
      if (viewMode === 'board') {
        await loadBoard();
      } else if (viewMode === 'qa') {
        await loadQAData();
      } else if (viewMode === 'files') {
        await loadFiles(currentFolderId);
      }
    }
    setRefreshing(false);
  }, [selectedProject, viewMode, currentFolderId]);

  const handleStatusChange = async (task: Task, newStatus: string) => {
    try {
      await apiClient.patch(`/api/projects/tasks/${task.id}/status?status=${newStatus}`);
      loadBoard();
    } catch (error) {
      console.error('Failed to update task status:', error);
    }
  };

  const handleCreateTask = async () => {
    if (!selectedProject || !newTaskTitle.trim()) return;

    try {
      setCreatingTask(true);
      await apiClient.post(`/api/projects/${selectedProject.id}/tasks`, {
        title: newTaskTitle.trim(),
        description: newTaskDescription.trim() || null,
        task_type: newTaskType,
        priority: newTaskPriority,
      });

      // Reset form and close modal
      setNewTaskTitle('');
      setNewTaskDescription('');
      setNewTaskType('task');
      setNewTaskPriority(null);
      setShowCreateTask(false);

      // Reload board
      loadBoard();
      Alert.alert('Success', 'Task created successfully');
    } catch (error) {
      console.error('Failed to create task:', error);
      Alert.alert('Error', 'Failed to create task');
    } finally {
      setCreatingTask(false);
    }
  };

  const toggleCheckItem = (commitId: string, itemId: string) => {
    setCheckedItems(prev => {
      const current = prev[commitId] || [];
      const newChecked = current.includes(itemId)
        ? current.filter(id => id !== itemId)
        : [...current, itemId];
      return { ...prev, [commitId]: newChecked };
    });
  };

  const saveQAResult = async (commitId: string, status: 'passed' | 'failed' | 'skipped') => {
    try {
      await apiClient.post(`/api/projects/commits/${commitId}/qa`, {
        checked_items: checkedItems[commitId] || [],
        notes: qaNote[commitId] || null,
        status,
      });
      // Remove from pending list
      setPendingTasks(prev =>
        prev
          .map(task => ({
            ...task,
            commits: task.commits.filter(c => c.id !== commitId),
          }))
          .filter(task => task.commits.length > 0)
      );
      Alert.alert('Success', `QA marked as ${status}`);
    } catch (error) {
      console.error('Failed to save QA result:', error);
      Alert.alert('Error', 'Failed to save QA result');
    }
  };

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  const totalPending = pendingTasks.reduce((sum, t) => sum + t.commits.length, 0);

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity
          style={styles.projectSelector}
          onPress={() => setShowProjectPicker(true)}
        >
          <Text style={styles.projectName}>
            {selectedProject ? `[${selectedProject.prefix}] ${selectedProject.name}` : 'Select Project'}
          </Text>
          <Text style={styles.chevron}>▼</Text>
        </TouchableOpacity>
      </View>

      {/* Tabs */}
      <View style={styles.tabs}>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'board' && styles.tabActive]}
          onPress={() => setViewMode('board')}
        >
          <Text style={[styles.tabText, viewMode === 'board' && styles.tabTextActive]}>
            Board
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'qa' && styles.tabActive]}
          onPress={() => setViewMode('qa')}
        >
          <Text style={[styles.tabText, viewMode === 'qa' && styles.tabTextActive]}>
            QA {totalPending > 0 && `(${totalPending})`}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'files' && styles.tabActive]}
          onPress={() => setViewMode('files')}
        >
          <Text style={[styles.tabText, viewMode === 'files' && styles.tabTextActive]}>
            Files
          </Text>
        </TouchableOpacity>
      </View>

      {/* Content */}
      <ScrollView
        style={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
        }
      >
        {!selectedProject ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyIcon}>📋</Text>
            <Text style={styles.emptyTitle}>No Projects</Text>
            <Text style={styles.emptyText}>Create a project to start tracking tasks</Text>
          </View>
        ) : viewMode === 'board' ? (
          <TaskBoardView
            board={board}
            loading={boardLoading}
            onStatusChange={handleStatusChange}
          />
        ) : viewMode === 'qa' ? (
          <QAView
            checklist={checklist}
            pendingTasks={pendingTasks}
            loading={qaLoading}
            checkedItems={checkedItems}
            qaNote={qaNote}
            onToggleCheck={toggleCheckItem}
            onNoteChange={(commitId, note) =>
              setQaNote(prev => ({ ...prev, [commitId]: note }))
            }
            onSaveQA={saveQAResult}
          />
        ) : (
          <FilesView
            files={files}
            folders={folders}
            breadcrumb={breadcrumb}
            currentFolderId={currentFolderId}
            loading={filesLoading}
            uploading={uploading}
            showCreateFolder={showCreateFolder}
            newFolderName={newFolderName}
            onNavigateToFolder={navigateToFolder}
            onUploadFile={handleUploadFile}
            onCreateFolder={handleCreateFolder}
            onDeleteFile={handleDeleteFile}
            onDeleteFolder={handleDeleteFolder}
            onDownloadFile={handleDownloadFile}
            onShowCreateFolder={setShowCreateFolder}
            onNewFolderNameChange={setNewFolderName}
          />
        )}
      </ScrollView>

      {/* Project Picker Modal */}
      <Modal
        visible={showProjectPicker}
        animationType="slide"
        transparent
        onRequestClose={() => setShowProjectPicker(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>Select Project</Text>
            <ScrollView style={styles.projectList}>
              {projects.map(project => (
                <TouchableOpacity
                  key={project.id}
                  style={[
                    styles.projectItem,
                    selectedProject?.id === project.id && styles.projectItemSelected,
                  ]}
                  onPress={() => {
                    setSelectedProject(project);
                    setShowProjectPicker(false);
                  }}
                >
                  <Text style={styles.projectItemPrefix}>[{project.prefix}]</Text>
                  <Text style={styles.projectItemName}>{project.name}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <TouchableOpacity
              style={styles.modalClose}
              onPress={() => setShowProjectPicker(false)}
            >
              <Text style={styles.modalCloseText}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* Create Task Modal */}
      <Modal
        visible={showCreateTask}
        animationType="slide"
        transparent
        onRequestClose={() => setShowCreateTask(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.createTaskModal}>
            <Text style={styles.modalTitle}>New Task</Text>

            <ScrollView style={styles.createTaskForm}>
              {/* Title */}
              <Text style={styles.inputLabel}>Title *</Text>
              <TextInput
                style={styles.textInput}
                value={newTaskTitle}
                onChangeText={setNewTaskTitle}
                placeholder="Task title..."
                placeholderTextColor={colors.textSecondary}
                autoCorrect={true}
                autoCapitalize="sentences"
              />

              {/* Description */}
              <Text style={styles.inputLabel}>Description</Text>
              <TextInput
                style={[styles.textInput, styles.textInputMultiline]}
                value={newTaskDescription}
                onChangeText={setNewTaskDescription}
                placeholder="Task description (optional)..."
                placeholderTextColor={colors.textSecondary}
                multiline
                numberOfLines={3}
                autoCorrect={true}
                autoCapitalize="sentences"
              />

              {/* Task Type */}
              <Text style={styles.inputLabel}>Type</Text>
              <View style={styles.optionRow}>
                {(['feature', 'bug', 'task', 'chore'] as const).map(type => (
                  <TouchableOpacity
                    key={type}
                    style={[
                      styles.optionBtn,
                      newTaskType === type && styles.optionBtnActive,
                    ]}
                    onPress={() => setNewTaskType(type)}
                  >
                    <Text style={styles.optionIcon}>
                      {type === 'feature' ? '✨' : type === 'bug' ? '🐛' : type === 'task' ? '✅' : '🔧'}
                    </Text>
                    <Text style={[
                      styles.optionText,
                      newTaskType === type && styles.optionTextActive,
                    ]}>
                      {type.charAt(0).toUpperCase() + type.slice(1)}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>

              {/* Priority */}
              <Text style={styles.inputLabel}>Priority</Text>
              <View style={styles.optionRow}>
                {([null, 'low', 'medium', 'high', 'critical'] as const).map(priority => (
                  <TouchableOpacity
                    key={priority || 'none'}
                    style={[
                      styles.priorityBtn,
                      newTaskPriority === priority && styles.priorityBtnActive,
                      priority === 'critical' && styles.priorityBtnCritical,
                      priority === 'high' && styles.priorityBtnHigh,
                      priority === 'medium' && styles.priorityBtnMedium,
                      priority === 'low' && styles.priorityBtnLow,
                    ]}
                    onPress={() => setNewTaskPriority(priority)}
                  >
                    <Text style={[
                      styles.priorityText,
                      newTaskPriority === priority && styles.priorityTextActive,
                    ]}>
                      {priority ? priority.charAt(0).toUpperCase() + priority.slice(1) : 'None'}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </ScrollView>

            {/* Actions */}
            <View style={styles.createTaskActions}>
              <TouchableOpacity
                style={styles.cancelBtn}
                onPress={() => {
                  setShowCreateTask(false);
                  setNewTaskTitle('');
                  setNewTaskDescription('');
                  setNewTaskType('task');
                  setNewTaskPriority(null);
                }}
              >
                <Text style={styles.cancelBtnText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[
                  styles.createBtn,
                  (!newTaskTitle.trim() || creatingTask) && styles.createBtnDisabled,
                ]}
                onPress={handleCreateTask}
                disabled={!newTaskTitle.trim() || creatingTask}
              >
                <Text style={styles.createBtnText}>
                  {creatingTask ? 'Creating...' : 'Create Task'}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Floating Add Button (Board view only) */}
      {viewMode === 'board' && selectedProject && (
        <TouchableOpacity
          style={styles.fab}
          onPress={() => setShowCreateTask(true)}
        >
          <Text style={styles.fabText}>+</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

// Task Board View Component
function TaskBoardView({
  board,
  loading,
  onStatusChange,
}: {
  board: TaskBoard | null;
  loading: boolean;
  onStatusChange: (task: Task, status: string) => void;
}) {
  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (!board) {
    return (
      <View style={styles.emptyState}>
        <Text style={styles.emptyText}>No tasks yet</Text>
      </View>
    );
  }

  const columns = [
    { id: 'backlog', label: 'Backlog', tasks: board.backlog, color: colors.textSecondary },
    { id: 'in_progress', label: 'In Progress', tasks: board.in_progress, color: colors.primary },
    { id: 'in_qa', label: 'In QA', tasks: board.in_qa, color: colors.warning },
    { id: 'completed', label: 'Completed', tasks: board.completed, color: colors.success },
  ];

  return (
    <View style={styles.boardContainer}>
      {columns.map(column => (
        <View key={column.id} style={styles.column}>
          <View style={styles.columnHeader}>
            <View style={[styles.columnDot, { backgroundColor: column.color }]} />
            <Text style={styles.columnTitle}>{column.label}</Text>
            <Text style={styles.columnCount}>({column.tasks.length})</Text>
          </View>
          {column.tasks.map(task => (
            <TaskCard
              key={task.id}
              task={task}
              onStatusChange={onStatusChange}
            />
          ))}
          {column.tasks.length === 0 && (
            <Text style={styles.emptyColumn}>No tasks</Text>
          )}
        </View>
      ))}
    </View>
  );
}

// Task Card Component
function TaskCard({
  task,
  onStatusChange,
}: {
  task: Task;
  onStatusChange: (task: Task, status: string) => void;
}) {
  const [showActions, setShowActions] = useState(false);

  const typeEmoji: Record<string, string> = {
    feature: '✨',
    bug: '🐛',
    task: '✅',
    chore: '🔧',
  };

  const priorityColors: Record<string, string> = {
    critical: colors.error,
    high: colors.hues.orange,
    medium: colors.hues.amber,
    low: colors.textSecondary,
  };

  return (
    <TouchableOpacity
      style={[
        styles.taskCard,
        task.priority && {
          borderLeftWidth: 3,
          borderLeftColor: priorityColors[task.priority],
        },
      ]}
      onPress={() => setShowActions(!showActions)}
    >
      <View style={styles.taskHeader}>
        <Text style={styles.taskType}>{typeEmoji[task.task_type] || '✅'}</Text>
        <Text style={styles.taskTag}>{task.tag}</Text>
        {task.commit_count > 0 && (
          <Text style={styles.commitCount}>📝 {task.commit_count}</Text>
        )}
      </View>
      <Text style={styles.taskTitle} numberOfLines={2}>
        {task.title}
      </Text>

      {showActions && (
        <View style={styles.taskActions}>
          {task.status !== 'backlog' && (
            <TouchableOpacity
              style={styles.actionBtn}
              onPress={() => onStatusChange(task, 'backlog')}
            >
              <Text style={styles.actionBtnText}>→ Backlog</Text>
            </TouchableOpacity>
          )}
          {task.status !== 'in_progress' && (
            <TouchableOpacity
              style={styles.actionBtn}
              onPress={() => onStatusChange(task, 'in_progress')}
            >
              <Text style={styles.actionBtnText}>→ In Progress</Text>
            </TouchableOpacity>
          )}
          {task.status !== 'in_qa' && (
            <TouchableOpacity
              style={styles.actionBtn}
              onPress={() => onStatusChange(task, 'in_qa')}
            >
              <Text style={styles.actionBtnText}>→ In QA</Text>
            </TouchableOpacity>
          )}
          {task.status !== 'completed' && (
            <TouchableOpacity
              style={[styles.actionBtn, styles.actionBtnSuccess]}
              onPress={() => onStatusChange(task, 'completed')}
            >
              <Text style={[styles.actionBtnText, styles.actionBtnTextSuccess]}>
                ✓ Complete
              </Text>
            </TouchableOpacity>
          )}
        </View>
      )}
    </TouchableOpacity>
  );
}

// QA View Component
function QAView({
  checklist,
  pendingTasks,
  loading,
  checkedItems,
  qaNote,
  onToggleCheck,
  onNoteChange,
  onSaveQA,
}: {
  checklist: QAChecklistItem[];
  pendingTasks: QAPendingTask[];
  loading: boolean;
  checkedItems: Record<string, string[]>;
  qaNote: Record<string, string>;
  onToggleCheck: (commitId: string, itemId: string) => void;
  onNoteChange: (commitId: string, note: string) => void;
  onSaveQA: (commitId: string, status: 'passed' | 'failed' | 'skipped') => void;
}) {
  const [expandedTask, setExpandedTask] = useState<string | null>(
    pendingTasks[0]?.task_id || null
  );

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (checklist.length === 0) {
    return (
      <View style={styles.emptyState}>
        <Text style={styles.emptyIcon}>📋</Text>
        <Text style={styles.emptyTitle}>No QA Checklist</Text>
        <Text style={styles.emptyText}>
          Configure checklist items in web settings to start QA testing
        </Text>
      </View>
    );
  }

  if (pendingTasks.length === 0) {
    return (
      <View style={styles.emptyState}>
        <Text style={styles.emptyIcon}>✅</Text>
        <Text style={styles.emptyTitle}>All Caught Up!</Text>
        <Text style={styles.emptyText}>No commits pending QA review</Text>
      </View>
    );
  }

  return (
    <View style={styles.qaContainer}>
      {pendingTasks.map(task => (
        <View key={task.task_id} style={styles.qaTaskGroup}>
          <TouchableOpacity
            style={styles.qaTaskHeader}
            onPress={() =>
              setExpandedTask(expandedTask === task.task_id ? null : task.task_id)
            }
          >
            <View style={styles.qaTaskInfo}>
              <Text style={styles.qaTaskTag}>{task.task_tag}</Text>
              <Text style={styles.qaTaskTitle} numberOfLines={1}>
                {task.task_title}
              </Text>
            </View>
            <Text style={styles.qaChevron}>
              {expandedTask === task.task_id ? '▲' : '▼'}
            </Text>
          </TouchableOpacity>

          {expandedTask === task.task_id &&
            task.commits.map(commit => {
              const commitChecked = checkedItems[commit.id] || [];
              const allChecked = checklist.every(item =>
                commitChecked.includes(item.id)
              );

              return (
                <View key={commit.id} style={styles.qaCommit}>
                  <View style={styles.commitInfo}>
                    <Text style={styles.commitSha}>{commit.sha.slice(0, 7)}</Text>
                    <Text style={styles.commitMessage} numberOfLines={2}>
                      {commit.message}
                    </Text>
                    <Text style={styles.commitMeta}>
                      {commit.author_name} · {new Date(commit.committed_at).toLocaleDateString()}
                    </Text>
                  </View>

                  {/* Checklist */}
                  <View style={styles.checklist}>
                    {checklist.map(item => (
                      <TouchableOpacity
                        key={item.id}
                        style={styles.checkItem}
                        onPress={() => onToggleCheck(commit.id, item.id)}
                      >
                        <View
                          style={[
                            styles.checkbox,
                            commitChecked.includes(item.id) && styles.checkboxChecked,
                          ]}
                        >
                          {commitChecked.includes(item.id) && (
                            <Text style={styles.checkmark}>✓</Text>
                          )}
                        </View>
                        <Text style={styles.checkLabel}>{item.label}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>

                  {/* Notes */}
                  <TextInput
                    style={styles.noteInput}
                    placeholder="Add notes (optional)..."
                    placeholderTextColor={colors.textSecondary}
                    value={qaNote[commit.id] || ''}
                    onChangeText={text => onNoteChange(commit.id, text)}
                    multiline
                    autoCorrect={true}
                    autoCapitalize="sentences"
                  />

                  {/* Actions */}
                  <View style={styles.qaActions}>
                    <TouchableOpacity
                      style={[
                        styles.qaBtn,
                        styles.qaBtnPass,
                        !allChecked && styles.qaBtnDisabled,
                      ]}
                      onPress={() => allChecked && onSaveQA(commit.id, 'passed')}
                      disabled={!allChecked}
                    >
                      <Text style={styles.qaBtnText}>✓ Pass</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[styles.qaBtn, styles.qaBtnFail]}
                      onPress={() => onSaveQA(commit.id, 'failed')}
                    >
                      <Text style={styles.qaBtnText}>✗ Fail</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[styles.qaBtn, styles.qaBtnSkip]}
                      onPress={() => onSaveQA(commit.id, 'skipped')}
                    >
                      <Text style={styles.qaBtnText}>Skip</Text>
                    </TouchableOpacity>
                  </View>
                  {!allChecked && (
                    <Text style={styles.qaHint}>Check all items to pass</Text>
                  )}
                </View>
              );
            })}
        </View>
      ))}
    </View>
  );
}

// ============================================================================
// FILES VIEW COMPONENT
// ============================================================================

interface FilesViewProps {
  files: ProjectFile[];
  folders: ProjectFolder[];
  breadcrumb: ProjectFolder[];
  currentFolderId: string | null;
  loading: boolean;
  uploading: boolean;
  showCreateFolder: boolean;
  newFolderName: string;
  onNavigateToFolder: (folderId: string | null) => void;
  onUploadFile: () => void;
  onCreateFolder: () => void;
  onDeleteFile: (fileId: string) => void;
  onDeleteFolder: (folderId: string) => void;
  onDownloadFile: (file: ProjectFile) => void;
  onShowCreateFolder: (show: boolean) => void;
  onNewFolderNameChange: (name: string) => void;
}

function FilesView({
  files,
  folders,
  breadcrumb,
  loading,
  uploading,
  showCreateFolder,
  newFolderName,
  onNavigateToFolder,
  onUploadFile,
  onCreateFolder,
  onDeleteFile,
  onDeleteFolder,
  onDownloadFile,
  onShowCreateFolder,
  onNewFolderNameChange,
}: FilesViewProps) {
  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  const getFileIcon = (mimeType: string | null) => {
    if (!mimeType) return '📄';
    if (mimeType.startsWith('text/')) return '📝';
    if (mimeType === 'application/pdf') return '📕';
    if (mimeType.startsWith('image/')) return '🖼️';
    return '📄';
  };

  return (
    <View style={styles.filesContainer}>
      {/* Header Actions */}
      <View style={styles.filesHeader}>
        <TouchableOpacity
          style={styles.filesBtn}
          onPress={() => onShowCreateFolder(true)}
        >
          <Text style={styles.filesBtnText}>📁 New Folder</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.filesBtn, styles.filesBtnPrimary]}
          onPress={onUploadFile}
          disabled={uploading}
        >
          <Text style={styles.filesBtnTextPrimary}>
            {uploading ? '⏳ Uploading...' : '⬆️ Upload'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Breadcrumb */}
      <View style={styles.breadcrumb}>
        <TouchableOpacity onPress={() => onNavigateToFolder(null)}>
          <Text style={styles.breadcrumbItem}>🏠 Root</Text>
        </TouchableOpacity>
        {breadcrumb.map((folder, index) => (
          <View key={folder.id} style={styles.breadcrumbSeparator}>
            <Text style={styles.breadcrumbSep}> › </Text>
            <TouchableOpacity onPress={() => onNavigateToFolder(folder.id)}>
              <Text
                style={[
                  styles.breadcrumbItem,
                  index === breadcrumb.length - 1 && styles.breadcrumbActive,
                ]}
              >
                {folder.name}
              </Text>
            </TouchableOpacity>
          </View>
        ))}
      </View>

      {/* Create Folder Input */}
      {showCreateFolder && (
        <View style={styles.createFolderContainer}>
          <TextInput
            style={styles.createFolderInput}
            value={newFolderName}
            onChangeText={onNewFolderNameChange}
            placeholder="Folder name..."
            placeholderTextColor={colors.textSecondary}
            autoFocus
            autoCorrect={true}
            autoCapitalize="words"
          />
          <TouchableOpacity
            style={styles.createFolderBtn}
            onPress={onCreateFolder}
            disabled={!newFolderName.trim()}
          >
            <Text style={styles.createFolderBtnText}>Create</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.createFolderCancel}
            onPress={() => {
              onShowCreateFolder(false);
              onNewFolderNameChange('');
            }}
          >
            <Text style={styles.createFolderCancelText}>Cancel</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Empty State */}
      {folders.length === 0 && files.length === 0 ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyIcon}>📂</Text>
          <Text style={styles.emptyTitle}>Folder is Empty</Text>
          <Text style={styles.emptyText}>Upload files or create folders</Text>
        </View>
      ) : (
        <View style={styles.filesList}>
          {/* Folders */}
          {folders.map((folder) => (
            <TouchableOpacity
              key={folder.id}
              style={styles.fileItem}
              onPress={() => onNavigateToFolder(folder.id)}
            >
              <Text style={styles.fileIcon}>📁</Text>
              <View style={styles.fileInfo}>
                <Text style={styles.fileName}>{folder.name}</Text>
                <Text style={styles.fileMeta}>Folder</Text>
              </View>
              <TouchableOpacity
                style={styles.fileAction}
                onPress={() => onDeleteFolder(folder.id)}
              >
                <Text style={styles.fileActionDelete}>🗑️</Text>
              </TouchableOpacity>
            </TouchableOpacity>
          ))}

          {/* Files */}
          {files.map((file) => (
            <View key={file.id} style={styles.fileItem}>
              <Text style={styles.fileIcon}>{getFileIcon(file.mime_type)}</Text>
              <View style={styles.fileInfo}>
                <Text style={styles.fileName} numberOfLines={1}>{file.filename}</Text>
                <Text style={styles.fileMeta}>{file.file_size_formatted}</Text>
              </View>
              <View style={styles.fileActions}>
                <TouchableOpacity
                  style={styles.fileAction}
                  onPress={() => onDownloadFile(file)}
                >
                  <Text>⬇️</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.fileAction}
                  onPress={() => onDeleteFile(file.id)}
                >
                  <Text style={styles.fileActionDelete}>🗑️</Text>
                </TouchableOpacity>
              </View>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 40,
  },
  header: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  projectSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.background,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 8,
  },
  projectName: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
  },
  chevron: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  tabs: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    paddingHorizontal: 16,
    gap: 8,
  },
  tab: {
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderBottomWidth: 2,
    borderBottomColor: 'transparent',
  },
  tabActive: {
    borderBottomColor: colors.primary,
  },
  tabText: {
    fontSize: fontSizes.md,
    color: colors.textSecondary,
  },
  tabTextActive: {
    color: colors.primary,
    fontWeight: '600',
  },
  content: {
    flex: 1,
  },
  emptyState: {
    padding: 40,
    alignItems: 'center',
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 16,
  },
  emptyTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: 8,
  },
  emptyText: {
    fontSize: fontSizes.md,
    color: colors.textSecondary,
    textAlign: 'center',
  },
  // Board styles
  boardContainer: {
    padding: 16,
  },
  column: {
    marginBottom: 24,
  },
  columnHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  columnDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  columnTitle: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
  },
  columnCount: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    marginLeft: 8,
  },
  emptyColumn: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    fontStyle: 'italic',
    textAlign: 'center',
    paddingVertical: 16,
  },
  taskCard: {
    backgroundColor: colors.surface,
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  taskHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  taskType: {
    fontSize: 14,
    marginRight: 8,
  },
  taskTag: {
    fontSize: fontSizes.xs,
    fontFamily: 'monospace',
    color: colors.textSecondary,
  },
  commitCount: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    marginLeft: 'auto',
  },
  taskTitle: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: '500',
  },
  taskActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  actionBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: colors.background,
    borderRadius: 6,
  },
  actionBtnSuccess: {
    backgroundColor: colors.success,
  },
  actionBtnText: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
  },
  actionBtnTextSuccess: {
    color: colors.text,
  },
  // QA styles
  qaContainer: {
    padding: 16,
  },
  qaTaskGroup: {
    backgroundColor: colors.surface,
    borderRadius: 8,
    marginBottom: 16,
    overflow: 'hidden',
  },
  qaTaskHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
    backgroundColor: colors.surface,
  },
  qaTaskInfo: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  qaTaskTag: {
    fontSize: fontSizes.sm,
    fontFamily: 'monospace',
    color: colors.primary,
    fontWeight: '600',
  },
  qaTaskTitle: {
    flex: 1,
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  qaChevron: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  qaCommit: {
    padding: 16,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  commitInfo: {
    marginBottom: 16,
  },
  commitSha: {
    fontSize: fontSizes.sm,
    fontFamily: 'monospace',
    color: colors.primary,
    marginBottom: 4,
  },
  commitMessage: {
    fontSize: fontSizes.sm,
    color: colors.text,
    marginBottom: 4,
  },
  commitMeta: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
  },
  checklist: {
    marginBottom: 16,
  },
  checkItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 2,
    borderColor: colors.border,
    marginRight: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  checkboxChecked: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  checkmark: {
    color: colors.text,
    fontSize: 12,
    fontWeight: 'bold',
  },
  checkLabel: {
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  noteInput: {
    backgroundColor: colors.background,
    borderRadius: 8,
    padding: 12,
    color: colors.text,
    fontSize: fontSizes.sm,
    marginBottom: 16,
    minHeight: 60,
    textAlignVertical: 'top',
  },
  qaActions: {
    flexDirection: 'row',
    gap: 8,
  },
  qaBtn: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 8,
    flex: 1,
    alignItems: 'center',
  },
  qaBtnPass: {
    backgroundColor: colors.success,
  },
  qaBtnFail: {
    backgroundColor: colors.error,
  },
  qaBtnSkip: {
    backgroundColor: colors.textSecondary,
  },
  qaBtnDisabled: {
    opacity: 0.5,
  },
  qaBtnText: {
    color: colors.text,
    fontWeight: '600',
    fontSize: fontSizes.sm,
  },
  qaHint: {
    fontSize: fontSizes.xs,
    color: colors.warning,
    marginTop: 8,
    textAlign: 'center',
  },
  // Modal styles
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    maxHeight: '70%',
  },
  modalTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    padding: 16,
    textAlign: 'center',
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  projectList: {
    maxHeight: 300,
  },
  projectItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  projectItemSelected: {
    backgroundColor: colors.primary + '20',
  },
  projectItemPrefix: {
    fontSize: fontSizes.sm,
    fontFamily: 'monospace',
    color: colors.primary,
    marginRight: 8,
  },
  projectItemName: {
    fontSize: fontSizes.md,
    color: colors.text,
  },
  modalClose: {
    padding: 16,
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  modalCloseText: {
    fontSize: fontSizes.md,
    color: colors.textSecondary,
  },
  // Files View Styles
  filesContainer: {
    padding: 16,
  },
  filesHeader: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 16,
  },
  filesBtn: {
    flex: 1,
    paddingVertical: 12,
    backgroundColor: colors.surface,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  filesBtnPrimary: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  filesBtnText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  filesBtnTextPrimary: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  breadcrumb: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    marginBottom: 16,
    paddingHorizontal: 4,
  },
  breadcrumbItem: {
    fontSize: fontSizes.sm,
    color: colors.primary,
  },
  breadcrumbActive: {
    color: colors.text,
    fontWeight: '600',
  },
  breadcrumbSeparator: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  breadcrumbSep: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  createFolderContainer: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 16,
    padding: 12,
    backgroundColor: colors.surface,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  createFolderInput: {
    flex: 1,
    backgroundColor: colors.background,
    borderRadius: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  createFolderBtn: {
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 6,
    justifyContent: 'center',
  },
  createFolderBtnText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  createFolderCancel: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    justifyContent: 'center',
  },
  createFolderCancelText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  filesList: {
    gap: 1,
    backgroundColor: colors.surface,
    borderRadius: 12,
    overflow: 'hidden',
  },
  fileItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 14,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  fileIcon: {
    fontSize: 24,
    marginRight: 12,
  },
  fileInfo: {
    flex: 1,
  },
  fileName: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '500',
  },
  fileMeta: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    marginTop: 2,
  },
  fileActions: {
    flexDirection: 'row',
    gap: 8,
  },
  fileAction: {
    padding: 8,
  },
  fileActionDelete: {
    opacity: 0.7,
  },
  // Create Task Modal Styles
  createTaskModal: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    maxHeight: '85%',
  },
  createTaskForm: {
    padding: 16,
    maxHeight: 400,
  },
  inputLabel: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.text,
    marginBottom: 8,
    marginTop: 12,
  },
  textInput: {
    backgroundColor: colors.background,
    borderRadius: 8,
    padding: 12,
    color: colors.text,
    fontSize: fontSizes.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  textInputMultiline: {
    minHeight: 80,
    textAlignVertical: 'top',
  },
  optionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  optionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: colors.background,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 4,
  },
  optionBtnActive: {
    backgroundColor: colors.primary + '20',
    borderColor: colors.primary,
  },
  optionIcon: {
    fontSize: 14,
  },
  optionText: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  optionTextActive: {
    color: colors.primary,
    fontWeight: '500',
  },
  priorityBtn: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: colors.background,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  priorityBtnActive: {
    borderWidth: 2,
  },
  priorityBtnCritical: {
    borderColor: colors.error,
  },
  priorityBtnHigh: {
    borderColor: colors.hues.orange,
  },
  priorityBtnMedium: {
    borderColor: colors.hues.amber,
  },
  priorityBtnLow: {
    borderColor: colors.textSecondary,
  },
  priorityText: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  priorityTextActive: {
    fontWeight: '600',
    color: colors.text,
  },
  createTaskActions: {
    flexDirection: 'row',
    padding: 16,
    gap: 12,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  cancelBtn: {
    flex: 1,
    paddingVertical: 14,
    alignItems: 'center',
    borderRadius: 8,
    backgroundColor: colors.background,
  },
  cancelBtnText: {
    fontSize: fontSizes.md,
    color: colors.textSecondary,
    fontWeight: '500',
  },
  createBtn: {
    flex: 2,
    paddingVertical: 14,
    alignItems: 'center',
    borderRadius: 8,
    backgroundColor: colors.primary,
  },
  createBtnDisabled: {
    opacity: 0.5,
  },
  createBtnText: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '600',
  },
  // Floating Action Button
  fab: {
    position: 'absolute',
    bottom: 24,
    right: 24,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: colors.shadow,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 6,
    elevation: 8,
  },
  fabText: {
    fontSize: 28,
    color: colors.text,
    fontWeight: '300',
    marginTop: -2,
  },
});
