import React, { useState, useEffect, useRef } from 'react';
import { initializeApp } from 'firebase/app';
import { getAuth, signInAnonymously, signInWithCustomToken, onAuthStateChanged } from 'firebase/auth';
import { getFirestore, collection, query, where, getDocs, addDoc, updateDoc, deleteDoc, onSnapshot, doc, orderBy } from 'firebase/firestore';
// import Papa from 'papaparse'; // Removed: PapaParse will be loaded from CDN
import { parseISO, format } from 'date-fns'; // For date formatting

// Initialize Firebase (these globals are provided by the Canvas environment)
const firebaseConfig = typeof __firebase_config !== 'undefined' ? JSON.parse(__firebase_config) : {};
const appId = typeof __app_id !== 'undefined' ? __app_id : 'default-app-id';

// Define the main App component
const App = () => {
    const [db, setDb] = useState(null);
    const [auth, setAuth] = useState(null);
    const [userId, setUserId] = useState(null);
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [transactions, setTransactions] = useState([]);
    const [categories, setCategories] = useState([]);
    const [rules, setRules] = useState({}); // For automatic categorization rules: {keyword: category}
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState('');
    const [newCategoryName, setNewCategoryName] = useState('');

    const fileInputRef = useRef(null);

    // Effect for Firebase initialization and authentication
    useEffect(() => {
        const initializeFirebase = async () => {
            try {
                const app = initializeApp(firebaseConfig);
                const firestore = getFirestore(app);
                const firebaseAuth = getAuth(app);

                setDb(firestore);
                setAuth(firebaseAuth);

                // Sign in anonymously if no initial auth token is provided
                const initialAuthToken = typeof __initial_auth_token !== 'undefined' ? __initial_auth_token : null;

                if (initialAuthToken) {
                    await signInWithCustomToken(firebaseAuth, initialAuthToken);
                } else {
                    await signInAnonymously(firebaseAuth);
                }

                // Listen for auth state changes
                onAuthStateChanged(firebaseAuth, (user) => {
                    if (user) {
                        setUserId(user.uid);
                        setIsAuthenticated(true);
                        setMessage(`Authenticated as user: ${user.uid}`);
                    } else {
                        setUserId(null);
                        setIsAuthenticated(false);
                        setMessage('Not authenticated. Please sign in or enable anonymous authentication.');
                    }
                });
            } catch (error) {
                console.error("Error initializing Firebase:", error);
                setMessage(`Error initializing Firebase: ${error.message}`);
            }
        };

        initializeFirebase();
    }, []);

    // Effect for fetching categories and rules when authenticated
    useEffect(() => {
        if (!db || !userId) return;

        // Fetch categories
        const categoriesColRef = collection(db, `artifacts/${appId}/users/${userId}/categories`);
        const unsubscribeCategories = onSnapshot(categoriesColRef, (snapshot) => {
            const fetchedCategories = snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
            setCategories(fetchedCategories);
        });

        // Fetch rules for auto-categorization
        const rulesColRef = collection(db, `artifacts/${appId}/users/${userId}/rules`);
        const unsubscribeRules = onSnapshot(rulesColRef, (snapshot) => {
            const fetchedRules = {};
            snapshot.docs.forEach(doc => {
                const rule = doc.data();
                fetchedRules[rule.keyword.toLowerCase()] = rule.category; // Store as {keyword: category}
            });
            setRules(fetchedRules);
        });

        return () => {
            unsubscribeCategories();
            unsubscribeRules();
        };
    }, [db, userId]);

    // Effect for fetching transactions when authenticated
    useEffect(() => {
        if (!db || !userId) return;

        const transactionsColRef = collection(db, `artifacts/${appId}/users/${userId}/transactions`);
        // Note: orderBy is commented out as it can cause index errors without proper Firestore indexing setup.
        // Data will be sorted in client-side memory if needed.
        const q = query(transactionsColRef); //, orderBy('date', 'desc'));

        const unsubscribeTransactions = onSnapshot(q, (snapshot) => {
            const fetchedTransactions = snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
            // Sort by date in descending order (newest first) client-side
            fetchedTransactions.sort((a, b) => {
                const dateA = a.date instanceof Date ? a.date : parseISO(a.date);
                const dateB = b.date instanceof Date ? b.date : parseISO(b.date);
                return dateB.getTime() - dateA.getTime();
            });
            setTransactions(fetchedTransactions);
        }, (error) => {
            console.error("Error fetching transactions:", error);
            setMessage(`Error fetching transactions: ${error.message}`);
        });

        return () => unsubscribeTransactions();
    }, [db, userId]);

    // Function to handle file upload
    const handleFileUpload = (event) => {
        const selectedFile = event.target.files[0];
        if (selectedFile) {
            setFile(selectedFile);
            setMessage(`Selected file: ${selectedFile.name}`);
        }
    };

    // Function to parse the CSV file
    const parseCsv = () => {
        if (!file) {
            setMessage('Please select a CSV file first.');
            return;
        }
        // Ensure PapaParse is available globally
        if (typeof window.Papa === 'undefined') {
            setMessage('PapaParse library is not loaded. Please try again or refresh.');
            return;
        }

        setLoading(true);
        setMessage('Parsing CSV...');

        window.Papa.parse(file, { // Use window.Papa
            header: true,
            skipEmptyLines: true,
            complete: async (results) => {
                let parsedTransactions = results.data.map(row => {
                    // Attempt to normalize common date, description, and amount columns
                    const date = row['Date'] || row['Transaction Date'] || row['Posting Date'] || '';
                    const description = row['Description'] || row['Payee'] || row['Transaction Details'] || '';
                    let amount = row['Amount'] || row['Debit'] || row['Credit'] || '';

                    // Handle debit/credit columns: if 'Debit' exists, it's negative. If 'Credit' exists, it's positive.
                    // If both exist, prioritize 'Amount' or handle based on specific file format.
                    if (row['Debit'] && parseFloat(row['Debit'])) {
                        amount = -parseFloat(row['Debit']);
                    } else if (row['Credit'] && parseFloat(row['Credit'])) {
                        amount = parseFloat(row['Credit']);
                    } else {
                        // Clean and parse the general amount field
                        amount = parseFloat(String(amount).replace(/[^0-9.-]+/g, ""));
                    }

                    // Simple auto-categorization based on existing rules
                    let category = 'Uncategorized';
                    const lowerDescription = String(description).toLowerCase();
                    for (const keyword in rules) {
                        if (lowerDescription.includes(keyword)) {
                            category = rules[keyword];
                            break; // Assign first matching rule
                        }
                    }

                    return {
                        date: date ? format(parseISO(date), 'yyyy-MM-dd') : '', // Format date to YYYY-MM-DD
                        description: description.trim(),
                        amount: isNaN(amount) ? 0 : amount,
                        category: category,
                        originalRow: row // Keep original row for debugging/completeness
                    };
                }).filter(tx => tx.description && !isNaN(tx.amount)); // Filter out invalid transactions

                // Save to Firestore
                if (db && userId) {
                    const transactionsColRef = collection(db, `artifacts/${appId}/users/${userId}/transactions`);
                    const batchSize = 50; // Firestore batch write limit
                    let savedCount = 0;

                    for (let i = 0; i < parsedTransactions.length; i += batchSize) {
                        const batch = [];
                        for (let j = 0; j < batchSize && (i + j) < parsedTransactions.length; j++) {
                            batch.push(parsedTransactions[i + j]);
                        }

                        // Check if transaction already exists (simple duplicate check based on date, description, amount)
                        // A more robust check might involve a unique ID from the bank statement or a hash.
                        const existingTransactionsQuery = query(
                            transactionsColRef,
                            where('date', 'in', batch.map(t => t.date).filter((v, i, a) => a.indexOf(v) === i)), // Filter by unique dates
                            where('userId', '==', userId)
                        );
                        const existingDocs = await getDocs(existingTransactionsQuery);
                        const existingTxSet = new Set(existingDocs.docs.map(doc => {
                            const data = doc.data();
                            return `${data.date}-${data.description}-${data.amount}`;
                        }));

                        for (const tx of batch) {
                            const txIdentifier = `${tx.date}-${tx.description}-${tx.amount}`;
                            if (!existingTxSet.has(txIdentifier)) {
                                await addDoc(transactionsColRef, { ...tx, userId: userId });
                                savedCount++;
                            }
                        }
                    }
                    setMessage(`Successfully parsed and added ${savedCount} new transactions.`);
                    setFile(null); // Clear file input
                    if (fileInputRef.current) {
                        fileInputRef.current.value = ''; // Reset file input element
                    }
                } else {
                    setMessage('Firestore or user not ready.');
                }
                setLoading(false);
            },
            error: (error) => {
                console.error("Error parsing CSV:", error);
                setMessage(`Error parsing CSV: ${error.message}`);
                setLoading(false);
            }
        });
    };

    // Function to update a transaction's category in Firestore
    const handleCategoryChange = async (transactionId, newCategory) => {
        if (!db || !userId) return;

        try {
            const transactionRef = doc(db, `artifacts/${appId}/users/${userId}/transactions`, transactionId);
            await updateDoc(transactionRef, { category: newCategory });

            // If a new category is assigned, consider adding a rule for future auto-categorization
            const transactionToUpdate = transactions.find(tx => tx.id === transactionId);
            if (transactionToUpdate && newCategory !== 'Uncategorized' && newCategory !== '') {
                const lowerDescription = transactionToUpdate.description.toLowerCase();
                // Simple rule: take the first few words or a significant part of the description as a keyword
                const keywordCandidate = lowerDescription.split(' ').slice(0, 2).join(' '); // Example: first two words
                // If the keyword doesn't exist or its category is different, update the rule
                if (keywordCandidate && (!rules[keywordCandidate] || rules[keywordCandidate] !== newCategory)) {
                    const rulesColRef = collection(db, `artifacts/${appId}/users/${userId}/rules`);
                    const q = query(rulesColRef, where('keyword', '==', keywordCandidate), where('userId', '==', userId));
                    const snapshot = await getDocs(q);

                    if (snapshot.empty) {
                        await addDoc(rulesColRef, { keyword: keywordCandidate, category: newCategory, userId: userId });
                        setMessage(`Rule added: '${keywordCandidate}' -> '${newCategory}'`);
                    } else {
                        // Update existing rule if category changed
                        const ruleDocRef = snapshot.docs[0].ref;
                        await updateDoc(ruleDocRef, { category: newCategory });
                        setMessage(`Rule updated: '${keywordCandidate}' -> '${newCategory}'`);
                    }
                }
            }
            setMessage('Transaction category updated.');
        } catch (error) {
            console.error('Error updating category:', error);
            setMessage(`Error updating category: ${error.message}`);
        }
    };

    // Function to add a new category
    const handleAddCategory = async () => {
        if (!newCategoryName.trim() || !db || !userId) {
            setMessage('Category name cannot be empty.');
            return;
        }
        if (categories.some(cat => cat.name.toLowerCase() === newCategoryName.trim().toLowerCase())) {
            setMessage('Category already exists.');
            return;
        }

        setLoading(true);
        try {
            const categoriesColRef = collection(db, `artifacts/${appId}/users/${userId}/categories`);
            await addDoc(categoriesColRef, { name: newCategoryName.trim(), userId: userId });
            setNewCategoryName('');
            setMessage('Category added successfully!');
        } catch (error) {
            console.error('Error adding category:', error);
            setMessage(`Error adding category: ${error.message}`);
        } finally {
            setLoading(false);
        }
    };

    // Function to delete a category
    const handleDeleteCategory = async (categoryId) => {
        if (!db || !userId) return;

        // Optionally, check if any transactions are using this category before deleting.
        // For simplicity, we'll allow deletion, but transactions might show 'undefined' category unless handled.
        setLoading(true);
        try {
            await deleteDoc(doc(db, `artifacts/${appId}/users/${userId}/categories`, categoryId));
            setMessage('Category deleted successfully!');
        } catch (error) {
            console.error('Error deleting category:', error);
            setMessage(`Error deleting category: ${error.message}`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-gradient-to-br from-purple-600 to-indigo-800 text-white p-6 font-inter antialiased">
            <script src="https://cdn.tailwindcss.com"></script>
            {/* PapaParse CDN for CSV parsing */}
            <script src="https://cdnjs.cloudflare.com/ajax/libs/PapaParse/5.4.1/papaparse.min.js"></script>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />

            {/* Global style for Inter font */}
            <style>
                {`
                body {
                    font-family: 'Inter', sans-serif;
                }
                select {
                    -webkit-appearance: none;
                    -moz-appearance: none;
                    appearance: none;
                    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'%3E%3Cpath fill='%236B7280' d='M10 12l-6-6 1.41-1.41L10 9.17l4.59-4.58L16 6z'/%3E%3C/svg%3E");
                    background-repeat: no-repeat;
                    background-position: right 0.75rem center;
                    background-size: 1.5em 1.5em;
                }
                `}
            </style>

            <div className="max-w-7xl mx-auto bg-gray-900 bg-opacity-80 rounded-xl shadow-2xl p-8 space-y-8 backdrop-blur-sm">
                <h1 className="text-4xl font-bold text-center text-purple-200 mb-8">
                    Personal Budgeting App
                </h1>

                {/* User Info & Authentication Status */}
                <div className="bg-gray-800 rounded-lg p-4 shadow-inner">
                    <p className="text-sm text-gray-400">
                        {isAuthenticated ? `You are logged in as: ${userId}` : 'Authenticating...'}
                    </p>
                    {message && (
                        <p className={`mt-2 text-sm ${message.includes('Error') ? 'text-red-400' : 'text-green-400'}`}>
                            {message}
                        </p>
                    )}
                </div>

                {/* File Upload Section */}
                <div className="bg-gray-800 rounded-lg p-6 shadow-lg border border-gray-700">
                    <h2 className="text-2xl font-semibold text-purple-300 mb-4">Upload Transactions (CSV)</h2>
                    <input
                        type="file"
                        ref={fileInputRef}
                        accept=".csv"
                        onChange={handleFileUpload}
                        className="block w-full text-sm text-gray-300
                            file:mr-4 file:py-2 file:px-4
                            file:rounded-full file:border-0
                            file:text-sm file:font-semibold
                            file:bg-purple-500 file:text-white
                            hover:file:bg-purple-600 cursor-pointer mb-4"
                    />
                    <button
                        onClick={parseCsv}
                        disabled={!file || loading || !isAuthenticated}
                        className="w-full bg-indigo-500 hover:bg-indigo-600 text-white font-bold py-2 px-4 rounded-lg
                            transition duration-300 ease-in-out transform hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed
                            shadow-md hover:shadow-lg"
                    >
                        {loading ? 'Processing...' : 'Process CSV'}
                    </button>
                </div>

                {/* Category Management Section */}
                <div className="bg-gray-800 rounded-lg p-6 shadow-lg border border-gray-700">
                    <h2 className="text-2xl font-semibold text-purple-300 mb-4">Manage Categories</h2>
                    <div className="flex flex-col sm:flex-row gap-4 mb-4">
                        <input
                            type="text"
                            placeholder="New category name"
                            value={newCategoryName}
                            onChange={(e) => setNewCategoryName(e.target.value)}
                            className="flex-grow p-3 rounded-lg bg-gray-700 text-white placeholder-gray-400 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-purple-500"
                            disabled={!isAuthenticated}
                        />
                        <button
                            onClick={handleAddCategory}
                            disabled={!newCategoryName.trim() || loading || !isAuthenticated}
                            className="bg-green-500 hover:bg-green-600 text-white font-bold py-3 px-6 rounded-lg
                                transition duration-300 ease-in-out transform hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed
                                shadow-md hover:shadow-lg"
                        >
                            Add Category
                        </button>
                    </div>
                    <div className="flex flex-wrap gap-2 mt-4">
                        {categories.map((cat) => (
                            <div
                                key={cat.id}
                                className="bg-gray-700 text-gray-200 text-sm px-3 py-1 rounded-full flex items-center shadow-inner"
                            >
                                {cat.name}
                                <button
                                    onClick={() => handleDeleteCategory(cat.id)}
                                    className="ml-2 text-red-400 hover:text-red-500 transition-colors duration-200"
                                    disabled={!isAuthenticated}
                                >
                                    &times;
                                </button>
                            </div>
                        ))}
                        {categories.length === 0 && <p className="text-gray-400 text-sm">No categories added yet.</p>}
                    </div>
                </div>


                {/* Transactions Display Section */}
                <div className="bg-gray-800 rounded-lg p-6 shadow-lg border border-gray-700">
                    <h2 className="text-2xl font-semibold text-purple-300 mb-4">Your Transactions</h2>
                    {transactions.length === 0 ? (
                        <p className="text-gray-400 text-center py-8">No transactions found. Upload a CSV to get started!</p>
                    ) : (
                        <div className="overflow-x-auto rounded-lg border border-gray-700 shadow-inner">
                            <table className="min-w-full divide-y divide-gray-700">
                                <thead className="bg-gray-700">
                                    <tr>
                                        <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Date</th>
                                        <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Description</th>
                                        <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Amount</th>
                                        <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Category</th>
                                    </tr>
                                </thead>
                                <tbody className="bg-gray-800 divide-y divide-gray-700">
                                    {transactions.map((tx) => (
                                        <tr key={tx.id} className="hover:bg-gray-700 transition-colors duration-150">
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{tx.date}</td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{tx.description}</td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm">
                                                <span className={`${tx.amount < 0 ? 'text-red-400' : 'text-green-400'} font-medium`}>
                                                    {tx.amount.toFixed(2)}
                                                </span>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm">
                                                <select
                                                    value={tx.category || 'Uncategorized'}
                                                    onChange={(e) => handleCategoryChange(tx.id, e.target.value)}
                                                    className="block w-full py-2 px-3 border border-gray-600 bg-gray-900 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm text-white"
                                                    disabled={!isAuthenticated}
                                                >
                                                    <option value="Uncategorized">Uncategorized</option>
                                                    {categories.map((cat) => (
                                                        <option key={cat.id} value={cat.name}>
                                                            {cat.name}
                                                        </option>
                                                    ))}
                                                </select>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default App;