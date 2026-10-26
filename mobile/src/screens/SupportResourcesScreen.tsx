import React from 'react';
import { Modal, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import SupportResourceCard from '../components/SupportResourceCard';
import supportResources from '../resources/support.json';
import { colors, radius } from '../theme';

export default function SupportResourcesScreen({ onClose }: { onClose: () => void }) {
  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={styles.container}>
        <ScrollView contentContainerStyle={styles.body} contentInsetAdjustmentBehavior="automatic">
          <SupportResourceCard card={supportResources} />
        </ScrollView>
        <View style={styles.footer}>
          <TouchableOpacity accessibilityRole="button" style={styles.done} onPress={onClose}>
            <Text style={styles.doneText}>Done</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: 24, paddingTop: 48 },
  footer: { padding: 16, paddingBottom: 40, borderTopWidth: 1, borderTopColor: colors.border },
  done: { backgroundColor: colors.primary, borderRadius: radius.md, minHeight: 48, justifyContent: 'center', alignItems: 'center' },
  doneText: { color: colors.onPrimary, fontSize: 16, fontWeight: '600' },
});
